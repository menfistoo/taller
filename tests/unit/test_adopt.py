"""adopt.py and `taller project adopt` — derive facts, interview intent, move tokens."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest
import yaml

import support
from taller import adopt, brands, constitution, doctor, paths, registry, scaffold
from taller.commands import brand as brand_command
from taller.commands import project as project_command
from taller.errors import ConfigError, GitError
from taller.prompter import ScriptedPrompter

OLD_CLAUDE_MD = "# Tool library\n\n" + "Always open SQLite through the context manager.\n" * 600
SITE_CSS = """/* The site's own styles */
:root {
  --color-primary: #1B365D;
  --color-accent: #c8a45c;
  --gap: 8px;
}

body { color: var(--color-primary); }
"""
FILES = {
    "app.py": "from flask import Flask\napp = Flask(__name__)\n\n\n@app.route('/')\n"
              "def index():\n    return 'hi'\n",
    "requirements.txt": "Flask==3.0.3\n",
    "static/css/site.css": SITE_CSS,
    "static/css/bootstrap.min.css": ":root{--bs-blue:#0d6efd}",
    "CLAUDE.md": OLD_CLAUDE_MD,
    "docker-compose.yml": "services: {}\n",
    "code-review/README.md": "old review agents\n",
    ".gitattributes": "*.png binary\n",
}
DISTILLED = {"summary": "A Flask app lending shared tools, one module, no blueprints.",
             "architecture_md": "## Shape\n\nEverything is in app.py; loans are rows, "
                                "never deleted, so history is the ledger."}
SETUP = {"setup.billing": "", "setup.host": "", "setup.language.code": "en",
         "setup.language.ui": "es", "setup.language.commits": "en"}
INTERVIEW = {
    "q1": "Lends shared tools between neighbours.", "q2": "A marketplace.",
    "q3": "Knowing who has which tool.", "q4": "2", "q5": "", "q6": "",
    "q7": "Tools and loans.", "q8": "n",
    "q9": "", "q10": "", "q11": "",                 # the inferences, kept with Enter
    "q12": ["Record a loan"],
}
NEW_BRAND = {"brand.slug": "harbour", "adopt.brand.intent": "Calm navy; gold for one action."}


@pytest.fixture
def repo(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(brand_command, "open_in_browser", lambda page: None)
    monkeypatch.setattr("taller.discovery._run_gh", lambda args: None)
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", json.dumps({
        "type": "result", "subtype": "success", "is_error": False, "session_id": "s",
        "result": "", "structured_output": DISTILLED,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }))
    return support.make_repo(paths.home() / "projects" / "tool-library", FILES)


def args(repo: Path, **extra) -> argparse.Namespace:
    return argparse.Namespace(path=str(repo), name=None, no_open=True, **extra)


def git(repo: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def on_main(repo: Path, relative: str) -> str:
    return git(repo, "cat-file", "blob", f"main:{relative}")


# --- derive ------------------------------------------------------------------

def test_derive_reads_the_repository_and_writes_nothing(repo: Path):
    before = support.tree_mtimes(repo)

    facts = adopt.derive(repo)

    assert support.tree_mtimes(repo) == before
    assert facts["profile"] == "flask-sqlite"
    assert facts["stylesheet"] == "static/css/site.css", "Bootstrap was taken for the brand"
    assert facts["tokens"]["--color-primary"] == "#1B365D"
    assert facts["deploy"] == "docker"
    assert facts["review_dirs"] == ["code-review"]
    assert facts["route_files"] == ["app.py"]
    assert facts["commits"] == 1
    assert facts["claude_md_tokens"] > 5000


def test_derive_works_on_a_bare_repository_with_no_history(tmp_home: Path):
    bare = support.make_repo(paths.home() / "projects" / "empty", {}, commit=False)

    facts = adopt.derive(bare)

    assert (facts["profile"], facts["tokens"], facts["claude_md"], facts["commits"]) == (
        None, {}, None, 0)


# --- the lift ----------------------------------------------------------------

def test_the_lift_replaces_root_with_an_import_and_is_idempotent():
    lifted = adopt.lift_stylesheet(SITE_CSS, "tokens.css")

    assert lifted.startswith('@import url("tokens.css");\n')
    assert ":root" not in lifted and "body { color: var(--color-primary); }" in lifted
    assert adopt.lift_stylesheet(lifted, "tokens.css") == lifted


def test_the_import_follows_a_charset_and_is_relative():
    lifted = adopt.lift_stylesheet('@charset "utf-8";\n:root { --a: #fff; }\np{}\n',
                                   adopt.import_href("static/site.css", "static/css/tokens.css"))

    assert lifted.startswith('@charset "utf-8";\n@import url("css/tokens.css");\n')


def test_existing_gitattributes_are_kept_and_taller_adds_only_its_lines():
    merged = adopt.merge_gitattributes("*.png binary\n", "static/css/tokens.css").decode()

    assert merged.startswith("*.png binary\n")
    assert "static/css/tokens.css text eol=lf merge=ours" in merged
    assert "* text=auto" not in merged, "adoption would renormalise the whole repository"
    assert adopt.merge_gitattributes(merged, "static/css/tokens.css").decode() == merged


# --- the whole adoption ------------------------------------------------------

def test_adoption_lifts_the_tokens_distils_claude_md_and_passes_doctor(repo: Path):
    prompter = ScriptedPrompter({**SETUP, **INTERVIEW, **NEW_BRAND, "brief": "1"})

    assert project_command.adopt(args(repo), prompter) == 0

    prompter.assert_all_used()
    assert git(repo, "log", "--format=%s").splitlines()[:2] == [
        "taller: resolve the constitution", "Adopt tool-library into Taller"]
    assert git(repo, "status", "--porcelain") == ""
    # The tokens moved rather than being flagged (4.2.1).
    assert constitution._resolve_brand("harbour")["tokens"] == {
        "--color-primary": "#1B365D", "--color-accent": "#c8a45c", "--gap": "8px"}
    site = (repo / "static/css/site.css").read_text(encoding="utf-8")
    assert site.startswith('@import url("tokens.css");') and ":root" not in site
    assert "--color-primary: #1B365D;" in on_main(repo, "static/css/tokens.css")
    # The old CLAUDE.md became a stub and a short architecture slice (A1).
    assert (repo / "CLAUDE.md").read_bytes() == scaffold.claude_md("tool-library")
    architecture = (paths.project_constitution(repo) / "architecture.md").read_text("utf-8")
    assert architecture.startswith(f"> {DISTILLED['summary']}")
    # Everything else.
    assert "*.png binary" in (repo / ".gitattributes").read_text(encoding="utf-8")
    assert registry.is_adopted(registry.get_project(repo))
    assert [c.name for c in doctor.run_checks() if c.status == doctor.FAIL] == []
    assert adopt.preamble_tokens(repo) <= 800                      # criterion 6
    assert adopt.local_content_chars(repo) < 2000                  # criterion 7
    assert "≈" in prompter.said[-1] and "Adopted tool-library" in prompter.said[-1]


def test_an_identical_palette_in_the_hub_is_proposed_and_not_duplicated(repo: Path):
    brands.write("harbour", {"--color-primary": "#1b365d", "--color-accent": "#C8A45C",
                             "--gap": "8px"}, "Existing.")
    prompter = ScriptedPrompter({**SETUP, **INTERVIEW, "brief": "1"})   # no brand.slug

    assert project_command.adopt(args(repo), prompter) == 0

    assert brands.list_brands() == ["harbour"]
    assert registry.get_project(repo)["brand"] == "harbour"
    assert ":root" not in (repo / "static/css/site.css").read_text(encoding="utf-8")


def test_a_failed_distillation_archives_the_old_file(repo: Path, monkeypatch):
    monkeypatch.setenv("STUB_CLAUDE_FAIL_EXIT", "1")
    prompter = ScriptedPrompter({**SETUP, **INTERVIEW, **NEW_BRAND, "brief": "1"})

    assert project_command.adopt(args(repo), prompter) == 0

    assert any("archived" in line for line in prompter.said)
    assert (repo / adopt.ARCHIVE_CLAUDE_MD).read_text(encoding="utf-8") == OLD_CLAUDE_MD
    assert not (paths.project_constitution(repo) / "architecture.md").exists()


def test_the_owner_can_choose_the_archive_over_the_summary(repo: Path):
    prompter = ScriptedPrompter({**SETUP, **INTERVIEW, **NEW_BRAND, "brief": ("3", "1")})

    assert project_command.adopt(args(repo), prompter) == 0

    assert (repo / adopt.ARCHIVE_CLAUDE_MD).exists()
    assert not (paths.project_constitution(repo) / "architecture.md").exists()


def test_cancel_changes_nothing(repo: Path):
    head = git(repo, "rev-parse", "HEAD")

    code = project_command.adopt(args(repo), ScriptedPrompter(
        {**SETUP, **INTERVIEW, **NEW_BRAND, "brief": "5"}))

    assert code == 1
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "status", "--porcelain", "--untracked-files=all") == ""
    assert brands.list_brands() == [] and registry.list_projects() == []


def test_a_dirty_repository_is_refused_before_any_question(repo: Path):
    (repo / "app.py").write_text("# work in progress\n", encoding="utf-8")

    with pytest.raises(GitError, match="uncommitted"):
        project_command.adopt(args(repo), ScriptedPrompter({}))


def test_adopting_twice_is_refused(repo: Path):
    project_command.adopt(args(repo), ScriptedPrompter(
        {**SETUP, **INTERVIEW, **NEW_BRAND, "brief": "1"}))

    with pytest.raises(ConfigError, match="already adopted"):
        project_command.adopt(args(repo), ScriptedPrompter({}))


# --- superseded review directories (criterion 10) ------------------------------

def test_adoption_removes_superseded_review_dirs(repo: Path):
    prompter = ScriptedPrompter({**SETUP, **INTERVIEW, **NEW_BRAND, "brief": "1"})

    assert project_command.adopt(args(repo), prompter) == 0

    said = "\n".join(prompter.said)
    assert "code-review/ is replaced by Taller's gates - removed in the adoption commit" in said
    assert not (repo / "code-review").exists()
    removed = git(repo, "show", "--name-status", "--format=", "HEAD~1").splitlines()
    assert "D\tcode-review/README.md" in removed
    assert git(repo, "status", "--porcelain") == ""


def test_the_owner_can_keep_them(repo: Path):
    prompter = ScriptedPrompter({**SETUP, **INTERVIEW, **NEW_BRAND, "brief": ("4", "1")})

    assert project_command.adopt(args(repo), prompter) == 0

    said = "\n".join(prompter.said)
    assert "code-review/ stays: you chose to keep it" in said
    assert on_main(repo, "code-review/README.md") == "old review agents\n"
