"""scaffold.py — profile scaffolds shaped by the answers; a project end to end.

Spec 11.4. `render` is pure; `create_project` is the library half of
`taller project new`, called once after the brief is approved.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import support
from taller import catalogue, constitution, gitio, paths, registry, scaffold
from taller.errors import ConfigError

ANSWERS = {
    "what_it_does": "Tracks which neighbour has borrowed which shared tool.",
    "what_it_is_not": "A marketplace: nothing is bought, sold or rented.",
    "must_never_break": "Knowing who has which tool right now.",
    "users": "team",
    "reach": "a private network",
    "phone": True,
    "stores": "Tools, neighbours and loans.",
    "sensitive_data": False,
    "deploy": "docker",
    "first_version": ["List the tools", "Record a loan", "Show who has what"],
}
LANGUAGE = {"code": "en", "ui": "es", "commits": "en"}


def facts(**changes) -> dict[str, str]:
    base = {"users": "team", "deploy": "docker", "sensitive_data": "no",
            "phone": "yes", "brand": "set"}
    base.update(changes)
    return base


def render(profile: str = "flask-sqlite", **changes) -> dict[str, bytes]:
    return scaffold.render(profile, name="toolshed", description="Tracks loans.",
                           facts=facts(**changes), ui_lang="es")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, check=True).stdout


@pytest.fixture
def identity(monkeypatch: pytest.MonkeyPatch):
    """Commits must not depend on the machine's git identity."""
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Taller Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def hub(tmp_home: Path, identity) -> Path:
    """A hub that has been through `setup` round 5: `language` is set."""
    support.write(paths.hub_config(), yaml.safe_dump({"language": LANGUAGE}))
    return tmp_home


def target(name: str = "toolshed") -> Path:
    return paths.home() / "projects" / name


# --- render ------------------------------------------------------------------

@pytest.mark.parametrize("profile", ["flask-sqlite", "static-site", "python-packaged"])
def test_render_is_deterministic_lf_and_complete(tmp_home: Path, profile: str):
    first, second = render(profile), render(profile)

    assert first == second
    assert first, "a scaffold rendered no files"
    assert not [path for path, data in first.items() if b"\r" in data]
    assert ".gitignore" in first and "README.md" in first


def test_deploy_local_omits_every_container_file(tmp_home: Path):
    files = render(deploy="local")

    for path in ("Dockerfile", "docker-compose.yml", "docker-compose.staging.yml",
                 "Caddyfile", ".dockerignore"):
        assert path not in files
    assert "Dockerfile" in render(deploy="docker")


def test_a_single_operator_gets_no_auth_scaffolding(tmp_home: Path):
    assert "auth.py" not in render(users="solo")
    assert "tests/test_auth.py" not in render(users="solo")
    assert "auth.py" in render(users="public")


def test_audit_logging_only_when_money_or_personal_data_is_involved(tmp_home: Path):
    without, with_audit = render(sensitive_data="no"), render(sensitive_data="yes")

    assert "audit.py" not in without
    assert b"audit_log" not in without["database.py"]
    assert "audit.py" in with_audit
    assert b"audit_log" in with_audit["database.py"]


def test_no_brand_means_no_brand_include(tmp_home: Path):
    assert "templates/_brand.html" not in render(brand="none")
    assert "templates/_brand.html" in render(brand="set")

    static_none = render("static-site", brand="none")["styles.css"]
    static_set = render("static-site", brand="set")["styles.css"]
    assert b"tokens.css" not in static_none
    assert b'@import url("tokens.css");' in static_set


def test_flask_template_syntax_survives_substitution(tmp_home: Path):
    base = render()["templates/base.html"].decode("utf-8")

    assert "{{ url_for('static', filename='css/app.css') }}" in base
    assert '{% include "_brand.html" ignore missing %}' in base
    assert '<html lang="es">' in base
    assert "{% block title %}toolshed{% endblock %}" in base
    assert "%%" not in base


# --- manifest errors ---------------------------------------------------------

@pytest.fixture
def fake_catalogue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A catalogue holding one scaffold the test writes."""
    root = tmp_path / "catalogue"
    monkeypatch.setattr(paths, "catalogue", lambda: root)

    def build(manifest: str, files: dict[str, str]) -> None:
        folder = root / "scaffolds" / "fake"
        support.write(folder / "manifest.yml", manifest)
        for name, text in files.items():
            support.write(folder / name, text)
    return build


@pytest.mark.parametrize("manifest, files, match", [
    ("files: [{path: a.txt, omit_when: {colour: [red]}}]", {"a.txt": "x"}, "colour"),
    ("files: [{path: a.txt, omit_when: {deploy: [cloud]}}]", {"a.txt": "x"}, "cloud"),
    ("files: [{path: a.txt, substitute: true}]", {"a.txt": "%%nmae%%"}, "nmae"),
    ("files: [{path: a.txt}]", {}, "a.txt"),
    ("files: [{path: a.txt}, {path: a.txt, source: b.txt}]",
     {"a.txt": "x", "b.txt": "y"}, "twice"),
    ("files: [{path: ../escape.txt}]", {"../escape.txt": "x"}, "escape"),
], ids=["unknown-fact", "unknown-value", "unknown-marker", "missing-source",
        "duplicate-destination", "path-escape"])
def test_manifest_mistakes_fail_loudly(tmp_home: Path, fake_catalogue, manifest, files, match):
    fake_catalogue(manifest, files)

    with pytest.raises(ConfigError, match=match):
        scaffold.render("fake", name="toolshed", description="d", facts=facts(), ui_lang="es")


def test_a_substituted_value_is_not_itself_substituted(tmp_home: Path, fake_catalogue):
    fake_catalogue("files: [{path: a.txt, substitute: true}]", {"a.txt": "%%description%%"})

    files = scaffold.render("fake", name="toolshed", description="100%%name%% sure",
                            facts=facts(), ui_lang="es")

    assert files["a.txt"] == b"100%%name%% sure"


# --- .gitattributes ----------------------------------------------------------

def test_gitattributes_pins_lf_and_marks_the_generated_files(tmp_home: Path):
    text = scaffold.render_gitattributes("static/css/tokens.css").decode("utf-8")

    assert "* text=auto eol=lf" in text.replace("  ", " ").replace("  ", " ")
    for generated in (".taller/resolved.json", ".taller/constitution/00-index.md",
                      "static/css/tokens.css"):
        assert any(line.startswith(generated) and "merge=ours" in line
                   for line in text.splitlines()), generated
    assert "tokens.css" not in scaffold.render_gitattributes(None).decode("utf-8")


# --- create_project ----------------------------------------------------------

def test_a_created_project_is_committed_registered_and_resolved(hub: Path):
    support.make_brand("harbour")

    report = scaffold.create_project(target(), name="toolshed", profile="flask-sqlite",
                                     brand="harbour", answers=ANSWERS)

    project = target()
    assert report.path == project.resolve()
    assert report.sync == gitio.SYNC_LOCAL
    assert git(project, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert git(project, "status", "--porcelain").strip() == ""
    assert registry.get_project(project)["profile"] == "flask-sqlite"
    assert git(project, "config", "merge.ours.driver").strip() == "true"
    tracked = git(project, "ls-files").splitlines()
    for path in (".taller/resolved.json", ".taller/constitution/00-index.md",
                 "static/css/tokens.css", ".gitattributes", "CLAUDE.md",
                 ".taller/constitution/product.md", ".taller/constitution/never.md",
                 ".taller/constitution/overrides.md", ".taller/queue.yml", "app.py"):
        assert path in tracked, path
    assert not (project / ".taller" / "work").exists(), "tickets are phase D"


def test_a_created_project_is_tamper_clean(hub: Path):
    support.make_brand("harbour")
    scaffold.create_project(target(), name="toolshed", profile="flask-sqlite",
                            brand="harbour", answers=ANSWERS)
    project = target()
    ruleset = constitution.resolve(project)

    def committed(path: str) -> bytes:
        return subprocess.run(["git", "-C", str(project), "cat-file", "blob", f"main:{path}"],
                              capture_output=True, check=True).stdout

    assert committed(".taller/resolved.json") == constitution.render_snapshot(ruleset)
    assert committed(".taller/constitution/00-index.md") == constitution.render_index(ruleset)
    assert committed("static/css/tokens.css") == constitution.render_tokens(ruleset)


def test_the_answers_land_in_the_constitution_and_the_queue(hub: Path):
    scaffold.create_project(target(), name="toolshed", profile="flask-sqlite",
                            brand=None, answers=ANSWERS)
    constitution_dir = paths.project_constitution(target())

    product = (constitution_dir / "product.md").read_text(encoding="utf-8")
    assert product.splitlines()[0] == f"> {ANSWERS['what_it_does']}"
    assert ANSWERS["must_never_break"] in product
    assert ANSWERS["what_it_is_not"] in (constitution_dir / "never.md").read_text(encoding="utf-8")
    queue = yaml.safe_load(paths.project_queue(target()).read_text(encoding="utf-8"))
    assert [entry["title"] for entry in queue["proposed"]] == ANSWERS["first_version"]
    assert "00-index.md" in (target() / "CLAUDE.md").read_text(encoding="utf-8")


def test_no_brand_means_no_token_file(hub: Path):
    scaffold.create_project(target(), name="toolshed", profile="flask-sqlite",
                            brand=None, answers=ANSWERS)

    assert not (target() / "static" / "css" / "tokens.css").exists()
    assert not (target() / "templates" / "_brand.html").exists()


def test_an_answer_cannot_inject_a_summary_or_burst_the_index(hub: Path):
    answers = dict(ANSWERS, what_it_does="> sneaky\n> second summary " + "word " * 300,
                   must_never_break="line one\n> also sneaky")

    scaffold.create_project(target(), name="toolshed", profile="flask-sqlite",
                            brand=None, answers=answers)

    product = (paths.project_constitution(target()) / "product.md").read_text(encoding="utf-8")
    summaries = [line for line in product.splitlines() if line.startswith("> ")]
    assert len(summaries) == 1
    assert len(summaries[0]) <= scaffold.SUMMARY_MAX + 2
    index = constitution.render_index(constitution.resolve(target()))
    assert constitution.estimate_tokens(index.decode("utf-8")) <= constitution.INDEX_TOKEN_BUDGET


# --- refusals write nothing --------------------------------------------------

def _nothing_written(hub_home: Path) -> None:
    assert not target().exists()
    if target().parent.exists():
        assert list(target().parent.iterdir()) == [], "a staging directory was left behind"
    assert registry.list_projects() == []
    assert catalogue.installed_profiles() == []


@pytest.mark.parametrize("change, match", [
    ({"name": "Tool Shed"}, "name"),
    ({"profile": "cobol-mainframe"}, "cobol-mainframe"),
    ({"brand": "ghost"}, "ghost"),
    ({"answers": dict(ANSWERS, users="everyone")}, "users"),
    ({"answers": dict(ANSWERS, deploy="the moon")}, "deploy"),
    ({"answers": {k: v for k, v in ANSWERS.items() if k != "what_it_does"}}, "what_it_does"),
], ids=["bad-name", "unknown-profile", "unknown-brand", "bad-users", "bad-deploy",
        "missing-answer"])
def test_a_refused_request_writes_nothing(hub: Path, change, match):
    kwargs = dict(name="toolshed", profile="flask-sqlite", brand=None, answers=ANSWERS)
    kwargs.update(change)

    with pytest.raises(ConfigError, match=match):
        scaffold.create_project(target(), **kwargs)
    _nothing_written(hub)


def test_an_unset_language_is_refused_and_writes_nothing(tmp_home: Path, identity):
    with pytest.raises(ConfigError, match="language"):
        scaffold.create_project(target(), name="toolshed", profile="flask-sqlite",
                                brand=None, answers=ANSWERS)
    _nothing_written(tmp_home)


def test_a_non_empty_target_is_refused_and_left_alone(hub: Path):
    support.write(target() / "precious.txt", "mine\n")

    with pytest.raises(ConfigError, match="not empty"):
        scaffold.create_project(target(), name="toolshed", profile="flask-sqlite",
                                brand=None, answers=ANSWERS)
    assert sorted(p.name for p in target().iterdir()) == ["precious.txt"]
    assert registry.list_projects() == []


def test_an_empty_target_directory_is_accepted(hub: Path):
    target().mkdir(parents=True)

    report = scaffold.create_project(target(), name="toolshed", profile="flask-sqlite",
                                     brand=None, answers=ANSWERS)

    assert report.sync == gitio.SYNC_LOCAL


# --- a scaffold that ships red tests teaches the owner to ignore red ----------

@pytest.mark.parametrize("profile, brand", [
    ("flask-sqlite", "harbour"), ("static-site", "harbour"), ("python-packaged", None),
])
def test_a_generated_projects_own_tests_pass(hub: Path, profile: str, brand: str | None):
    if brand:
        support.make_brand(brand)
    answers = dict(ANSWERS, sensitive_data=True, users="public")
    scaffold.create_project(target(), name="toolshed", profile=profile, brand=brand,
                            answers=answers)

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=target(), capture_output=True, text=True, env=env,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
