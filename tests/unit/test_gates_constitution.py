"""The constitution gate - every rule decidable, every finding by id and severity.

Spec 8.2, 9.1, 9.7, 15.2. Review Focus 5: a hex that is not a brand value.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import support
from taller import overrides
from taller.gates import constitution
from taller.gates import diff as diffs

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "broken-app"
OVERRIDES = ".taller/constitution/overrides.md"
HUB_SHA = "a3f9c21a3f9c21a3f9c21a3f9c21a3f9c21a3f9c"


def ruleset(**changes) -> dict:
    base = {
        "hub_sha": HUB_SHA,
        "language": {"code": "es", "ui": "es"},
        "non_suppressible": ["brand.hardcoded-font"],
        "overrides": [],
        "paths": {
            "layers": {"routes/**": ["database", "utils.*"], "database.py": []},
            "tests_dir": "tests",
            "brand_tokens": "static/css/tokens.css",
        },
    }
    base.update(changes)
    return base


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "-m", message)


def broken_app(tmp_path: Path) -> Path:
    """The fixture as a repo: README and `.taller/` on main, the rest on `ticket`."""
    repo = tmp_path / "broken-app"
    shutil.copytree(FIXTURE, repo)
    keep = {"README.md", ".taller"}
    parked = tmp_path / "parked"
    parked.mkdir()
    for entry in list(repo.iterdir()):
        if entry.name not in keep:
            shutil.move(str(entry), str(parked / entry.name))
    support.make_repo(repo, {})
    commit_all(repo, "chore: initial")
    git(repo, "checkout", "--quiet", "-b", "ticket")
    for entry in list(parked.iterdir()):
        shutil.move(str(entry), str(repo / entry.name))
    commit_all(repo, "Fixed stuff")
    return repo


@pytest.fixture
def verdict(tmp_path: Path, identity) -> dict:
    repo = broken_app(tmp_path)
    rules = ruleset(overrides=overrides.parse(
        (FIXTURE / OVERRIDES).read_text(encoding="utf-8"), source=OVERRIDES))
    return constitution.run(diffs.build(repo, "main", "ticket"), rules,
                            snapshot_sha="0" * 40)


def found(verdict: dict, rule: str) -> list[dict]:
    return [f for f in verdict["findings"] if f["rule"] == rule]


def change(files: dict[str, str], *, commits: tuple[str, ...] = ("feat: x",),
           status: str = "A") -> dict:
    """A Diff by hand: every line of every file added."""
    return {"base": "b", "head": "h", "tracked": sorted(files),
            "commits": [{"sha": f"{n:040d}", "message": m} for n, m in enumerate(commits)],
            "files": [{"path": path, "status": status, "content": text, "removed": [],
                       "added": [{"line": n, "text": t}
                                 for n, t in enumerate(text.splitlines(), 1)]}
                      for path, text in files.items()]}


# --- §15.2: every constitution-owned violation, by id and §9.7 severity ------------

@pytest.mark.parametrize("rule, severity, file, count", [
    ("brand.hardcoded-color", "HIGH", "static/css/site.css", 3),
    ("brand.hardcoded-font", "HIGH", "static/css/site.css", 1),
    ("constitution.layer-violation", "HIGH", "routes/__init__.py", 1),
    ("constitution.root-markdown", "MEDIUM", "NOTES.md", 1),
    ("constitution.single-use-script", "MEDIUM", "fix_thing.py", 1),
    ("constitution.commit-message-shape", "MEDIUM", "", 1),
    ("constitution.new-ui-literal", "MEDIUM", "templates/index.html", 2),
    ("constitution.resolved-snapshot-stale", "HIGH", ".taller/resolved.json", 1),
    ("constitution.override-without-reason", "HIGH", OVERRIDES, 1),
    ("constitution.override-expired", "HIGH", OVERRIDES, 1),
    ("constitution.override-not-permitted", "BLOCKER", OVERRIDES, 2),
])
def test_broken_app_violations_caught_by_id_and_severity(verdict, rule, severity, file, count):
    hits = found(verdict, rule)

    assert len(hits) == count, [h["message"] for h in hits]
    assert {h["severity"] for h in hits} == {severity}
    assert {h["file"] for h in hits} == {file}
    assert all(h["gate"] == "constitution" for h in hits)
    assert verdict["result"] == "fail"


def test_findings_carry_the_line_of_the_literal(verdict):
    assert sorted(h["line"] for h in found(verdict, "brand.hardcoded-color")) == [2, 3, 4]


def test_a_readme_and_a_permitted_import_are_not_findings(verdict):
    assert not [f for f in verdict["findings"] if f["file"] == "README.md"]
    layer = found(verdict, "constitution.layer-violation")
    assert "app" in layer[0]["message"] and "database" not in layer[0]["message"]


def test_a_branch_carrying_the_snapshot_is_a_blocker():
    verdict = constitution.run(change({".taller/resolved.json": "{}\n"}, status="M"), ruleset())

    hits = found(verdict, "constitution.resolved-snapshot-modified")
    assert [(h["severity"], h["file"]) for h in hits] == [("BLOCKER", ".taller/resolved.json")]


def test_a_current_snapshot_is_not_stale():
    verdict = constitution.run(change({"a.py": "x = 1\n"}), ruleset(), snapshot_sha=HUB_SHA)

    assert verdict["result"] == "pass" and verdict["findings"] == []


# --- Review Focus 5: legitimate hexes ------------------------------------------------

def test_the_generated_tokens_path_is_exempt():
    verdict = constitution.run(change({
        "static/css/tokens.css": ":root { --brand-primary: #1b365d; font-family: Lato; }\n"}),
        ruleset())

    assert verdict["findings"] == []


@pytest.mark.parametrize("path, text", [
    ("static/css/a.css", ".x { color: var(--brand-primary, #1b365d); }"),
    ("static/css/a.css", ".x { background: var(--a, var(--b, rgb(0, 0, 0))); }"),
    ("static/css/a.css", "#fade { opacity: 0; }"),
    ("static/css/a.css", "#add:hover, #bad > a { opacity: 1; }"),
    ("templates/a.html", '<a href="#top">{{ _("Subir") }}</a>'),
    ("templates/a.html", '<a href="#face" id="#bead">{{ x }}</a>'),
    ("templates/a.html", "<p>&#39;{{ x }}&#39;</p>"),
    ("app.py", 'PRIMARY = "#1b365d"'),
    ("tests/test_brand.py", 'assert colour == "#ffffff"'),
    ("static/css/a.css", ".x { font-family: var(--brand-font); }"),
    ("static/css/a.css", ".x { font-family: inherit; }"),
])
def test_fallbacks_anchors_and_python_hexes_are_not_colours(path, text):
    verdict = constitution.run(change({path: text + "\n"}), ruleset(language=None))

    assert verdict["findings"] == []


@pytest.mark.parametrize("path, text, count", [
    ("static/css/a.css", ".x { color: #fff; }", 1),
    ("static/css/a.css", ".x { color: #FFFFFF80; border: 1px solid #abc; }", 2),
    ("static/css/a.css", ".x { color: rgba(0, 0, 0, .5); background: hsl(0 0% 0%); }", 2),
    ("static/css/a.css", ".x {\n  box-shadow: 0 0 1px #000, 0 0 2px #111;\n}", 2),
    ("templates/a.html", '<div style="color:#1b365d">', 1),
    ("static/js/a.js", 'el.style.color = "#c8a45c";', 1),
])
def test_one_finding_per_literal(path, text, count):
    verdict = constitution.run(change({path: text + "\n"}), ruleset())

    assert len(found(verdict, "brand.hardcoded-color")) == count


def test_only_added_lines_are_judged():
    diff = change({"static/css/a.css": ".x { color: #fff; }\n"}, status="M")
    diff["files"][0]["added"] = []

    assert constitution.run(diff, ruleset())["findings"] == []


# --- new UI literals (§8.2) ----------------------------------------------------------

def test_new_ui_literal_only_when_language_ui_is_set():
    template = {"templates/a.html": '<button title="Close">Guardar</button>\n'
                                    "<p>{{ total }} {% if x %}{% endif %}</p>\n"
                                    "{# a note for developers #}\n"}

    on = constitution.run(change(template), ruleset())
    off = constitution.run(change(template), ruleset(language={"code": "es", "ui": "none"}))
    unset = constitution.run(change(template), ruleset(language=None))

    assert sorted(f["message"] for f in found(on, "constitution.new-ui-literal")) == [
        'New UI text: "Close"', 'New UI text: "Guardar"']
    assert found(off, "constitution.new-ui-literal") == []
    assert found(unset, "constitution.new-ui-literal") == []


# --- commit shape --------------------------------------------------------------------

@pytest.mark.parametrize("subject, ok", [
    ("feat(ui): add the ledger page", True),
    ("fix: a typo", True),
    ("perf(db-layer): index the entries", True),
    ("Fixed stuff", False),
    ("feat(UI): capital scope", False),
    ("feature: not a type", False),
    ("fix: " + "x" * 73, False),
    ("Merge branch 'main' into ticket", True),
])
def test_commit_shape_accepts_the_conventional_form(subject, ok):
    verdict = constitution.run(change({"a.py": "x = 1\n"}, commits=(subject,)), ruleset())

    assert (found(verdict, "constitution.commit-message-shape") == []) is ok


# --- files the gate cannot read ------------------------------------------------------

def test_an_unreadable_file_is_skipped_with_a_note():
    diff = change({"static/img/logo.css": ""})
    diff["files"][0]["content"] = None

    verdict = constitution.run(diff, ruleset())

    assert verdict["result"] == "pass"
    assert verdict["metrics"]["skipped"] == ["static/img/logo.css"]


def test_a_python_file_that_does_not_parse_is_skipped_not_a_crash():
    verdict = constitution.run(change({"routes/a.py": "def broken(:\n"}), ruleset())

    assert verdict["result"] == "pass"
    assert verdict["metrics"]["skipped"] == ["routes/a.py"]


# --- scan() ----------------------------------------------------------------------------

def test_scan_counts_pre_existing_violations(tmp_path: Path, identity):
    repo = broken_app(tmp_path)

    verdict = constitution.scan(diffs.tree(repo), ruleset())

    rules = [f["rule"] for f in verdict["findings"]]
    assert rules.count("brand.hardcoded-color") == 3
    assert rules.count("constitution.root-markdown") == 1
    assert rules.count("constitution.single-use-script") == 1
    assert rules.count("constitution.layer-violation") == 1
    assert "constitution.commit-message-shape" not in rules     # a tree has no commits
    assert "constitution.new-ui-literal" not in rules           # nothing is new in a scan
    assert "constitution.resolved-snapshot-modified" not in rules
    assert verdict["metrics"]["files_checked"] == len(diffs.tree(repo)["files"])
