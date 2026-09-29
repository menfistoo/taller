"""The adoption criteria of spec 16 that are phase A: 6, 7, 8 and 9.

An estate on disk - two Flask projects sharing one palette, one of them carrying
a long CLAUDE.md, a static site, and a repository whose remote no longer
resolves - taken through the real commands: `setup` in one pass, `project
adopt`, `project brief`, `brand edit`, and `doctor` after each.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import support
from taller import adopt, brands, cli, discovery, doctor, paths, registry
from taller.commands import brand as brand_command
from taller.prompter import ScriptedPrompter

PALETTE = ":root {\n  --color-primary: #1B365D;\n  --color-accent: #c8a45c;\n}\n\nbody { margin: 0; }\n"
OLD_CLAUDE_MD = "# Tool library\n\n" + "Open SQLite through the context manager, always.\n" * 560
FLASK = {"requirements.txt": "Flask==3.0.3\n",
         "app.py": "from flask import Flask\napp = Flask(__name__)\n"}
DISTILLED = {"summary": "One Flask module lending tools; loans are never deleted.",
             "architecture_md": "## Shape\n\nEverything is in app.py. A loan row is never "
                                "deleted: the table is the ledger."}
INTERVIEW = {"q1": "Lends shared tools.", "q2": "A marketplace.", "q3": "Who has which tool.",
             "q4": "2", "q5": "", "q6": "", "q7": "Tools and loans.", "q8": "n",
             "q9": "", "q10": "", "q11": "", "q12": ["Record a loan"], "brief": "1"}


@pytest.fixture
def estate(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    root = paths.home() / "estate"
    support.make_repo(root / "alpha", {**FLASK, "static/css/site.css": PALETTE,
                                       "CLAUDE.md": OLD_CLAUDE_MD},
                      origin="https://github.com/me/alpha")
    support.make_repo(root / "beta", {**FLASK, "static/css/site.css": PALETTE.lower()},
                      origin="https://github.com/me/beta")
    support.make_repo(root / "site", {"index.html": "<!doctype html>\n"})
    support.make_repo(root / "gone", FLASK, origin="https://github.com/me/gone")

    listing = [{"nameWithOwner": f"me/{n}", "url": f"https://github.com/me/{n}",
                "isPrivate": True} for n in ("alpha", "beta")]

    def gh(args, input=None):
        if args[:2] == ["auth", "status"]:
            return subprocess.CompletedProcess(args, 0, "✓ Logged in to github.com account me\n"
                                               "  - Token scopes: 'repo', 'workflow'\n", "")
        if args[:2] == ["repo", "list"]:
            return subprocess.CompletedProcess(args, 0, json.dumps(listing), "")
        # `doctor` asks GitHub about these projects now (spec 13, 15.4's F row):
        # read-only, and answered here as a repository with nothing to report.
        if args[:2] == ["run", "list"]:
            return subprocess.CompletedProcess(args, 0, "[]", "")
        if args[0] == "api" and "rulesets" in " ".join(args):
            return subprocess.CompletedProcess(args, 0, "[]", "")
        raise AssertionError(f"unexpected gh call: {args}")
    monkeypatch.setattr(discovery, "_run_gh", gh)
    monkeypatch.setattr(discovery, "_ls_remote", lambda repo: False)
    monkeypatch.setattr(brand_command, "open_in_browser", lambda page: None)
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", json.dumps({
        "type": "result", "subtype": "success", "is_error": False, "session_id": "s",
        "result": "", "structured_output": DISTILLED,
        "usage": {"input_tokens": 1, "output_tokens": 1}}))
    return root


def run(argv: list[str], answers: dict) -> ScriptedPrompter:
    prompter = ScriptedPrompter(answers)
    code = cli.main(argv, prompter)
    assert code == 0, "\n".join(prompter.said)
    prompter.assert_all_used()
    return prompter


def doctor_failures() -> list[str]:
    """Every failing check except the two a project on GitHub needs her to set up.

    After phase F, a project with a GitHub remote fails until its default branch
    is protected and `ci.taller_source` is set - both true, both hers to do, and
    neither about adoption. `test_github_flow` asserts they pass once set.
    """
    later = ("merging requires", "CI can install Taller")
    return [f"{c.name}: {c.detail}" for c in doctor.run_checks()
            if c.status == doctor.FAIL and not any(part in c.name for part in later)]


def test_an_estate_is_found_adopted_amended_and_rebranded(estate: Path):
    # Criterion 8: one pass registers every project and names the broken remote.
    said = run(["setup"], {
        "setup.billing": "", "setup.host": "", "setup.roots": str(estate),
        "setup.brand.alpha": "harbour", "setup.language.code": "en",
        "setup.language.ui": "es", "setup.language.commits": "en", "setup.review": "1",
    }).said
    assert sorted(e["name"] for e in registry.list_projects()) == ["alpha", "beta", "gone", "site"]
    assert any("gone → https://github.com/me/gone" in line for line in said)
    # Criterion 9: the shared palette became a brand by confirmation.
    assert brands.list_brands() == ["harbour"]
    assert registry.get_project(estate / "alpha")["brand"] == "harbour"
    assert doctor_failures() == []

    # Adoption: the inferences are kept with Enter.
    run(["project", "adopt", str(estate / "alpha"), "--no-open"], INTERVIEW)
    run(["project", "adopt", str(estate / "beta"), "--no-open"], INTERVIEW)
    alpha = estate / "alpha"
    assert adopt.preamble_tokens(alpha) <= 800                          # criterion 6
    assert adopt.local_content_chars(alpha) < 2000                      # criterion 7
    for name in ("alpha", "beta"):
        site = (estate / name / "static/css/site.css").read_text(encoding="utf-8")
        assert site.startswith('@import url("tokens.css");') and ":root" not in site
    assert brands.list_brands() == ["harbour"], "adoption duplicated the brand"
    assert doctor_failures() == []

    # The brief is re-runnable, as an amendment.
    run(["project", "brief", str(alpha), "--no-open"],
        {"brief.edit": ("2", ""), "q2": "A marketplace or a rental shop.", "brief.approve": ""})
    subjects = subprocess.run(["git", "-C", str(alpha), "log", "--format=%s", "-2"],
                              capture_output=True, text=True, encoding="utf-8").stdout
    assert "amend: brief (②)" in subjects
    assert doctor_failures() == []

    # A brand edit reaches both adopted projects and nothing else.
    said = run(["brand", "edit", "harbour", "--no-open"],
               {"brand.tokens": ("1", ""), "brand.token.name": "",
                "brand.token.value": "#0f7a5a", "brand.intent": "Calm.",
                "brand.approve": "1"}).said
    assert "alpha (" in said[-1] and "beta (" in said[-1]
    for name in ("alpha", "beta"):
        tokens = subprocess.run(["git", "-C", str(estate / name), "cat-file", "blob",
                                 "main:static/css/tokens.css"], capture_output=True,
                                text=True).stdout
        assert "#0f7a5a" in tokens
    assert doctor_failures() == []
    skipped = {c.name for c in doctor.run_checks() if c.status == doctor.SKIP}
    assert {"gone: not adopted yet", "site: not adopted yet"} <= skipped
