"""`taller setup` rounds 2-4 and 6, and `taller project discover` (spec 4.7).

Criteria 8 and 9: every discovered project registered in one pass with every
unresolvable remote named, and brands confirmed from shared palettes rather than
typed from scratch. Nothing is written before the review is approved, and
nothing is ever written into a discovered repository (decision B1).
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

import support
from taller import brands, catalogue, discovery, doctor, paths, registry
from taller.commands import project as project_command
from taller.commands import setup
from taller.prompter import ScriptedPrompter

PALETTE = ":root {\n  --color-primary: #1B365D;\n  --color-accent: #c8a45c;\n}\n"
SIGNED_IN = "✓ Logged in to github.com account me\n  - Token scopes: 'repo', 'workflow'\n"
LISTING = [{"nameWithOwner": f"me/{name}", "url": f"https://github.com/me/{name}",
            "isPrivate": True} for name in ("alpha", "beta", "never-cloned")]


@pytest.fixture
def estate(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    root = paths.home() / "estate"
    support.make_repo(root / "alpha", {"requirements.txt": "Flask\n",
                                       "static/css/site.css": PALETTE},
                      origin="https://github.com/me/alpha")
    support.make_repo(root / "beta", {"requirements.txt": "flask==3.0\n",
                                      "static/css/site.css": PALETTE.replace("1B365D", "1b365d")},
                      origin="git@github.com:me/beta.git")
    support.make_repo(root / "site", {"index.html": "<!doctype html>\n",
                                      "styles.css": ":root { --color-primary: #0f7a5a; }\n"})
    support.make_pdf(root / "site" / "docs" / "brand-guide.pdf", ["#0F7A5A"])
    support.make_repo(root / "blank", {}, commit=False)
    support.make_repo(root / "gone", {"requirements.txt": "Flask\n"},
                      origin="https://github.com/me/gone")

    def gh(args):
        if args[:2] == ["auth", "status"]:
            return subprocess.CompletedProcess(args, 0, SIGNED_IN, "")
        return subprocess.CompletedProcess(args, 0, json.dumps(LISTING), "")
    monkeypatch.setattr(discovery, "_run_gh", gh)
    monkeypatch.setattr(discovery, "_ls_remote", lambda repo: False)
    return root


def sheet(root: Path, **extra) -> dict:
    return {"setup.billing": "", "setup.host": "", "setup.roots": str(root),
            "setup.profile.blank": "2",               # python-packaged
            "setup.brand.alpha": "harbour", "setup.brand.site": "reef",
            "setup.language.code": "en", "setup.language.ui": "es",
            "setup.language.commits": "en", "setup.review": "1", **extra}


def test_one_pass_registers_everything_and_confirms_brands(estate: Path):
    before = support.tree_mtimes(estate)
    prompter = ScriptedPrompter(sheet(estate))

    assert setup.run(argparse.Namespace(), prompter) == 0

    prompter.assert_all_used()
    entries = {entry["name"]: entry for entry in registry.list_projects()}
    assert sorted(entries) == ["alpha", "beta", "blank", "gone", "site"]      # criterion 8
    assert not any(registry.is_adopted(entry) for entry in entries.values())
    assert (entries["alpha"]["brand"], entries["beta"]["brand"]) == ("harbour", "harbour")
    assert entries["site"]["brand"] == "reef" and entries["blank"]["profile"] == "python-packaged"
    assert brands.list_brands() == ["harbour", "reef"]                        # criterion 9
    assert catalogue.installed_profiles() == ["flask-sqlite", "python-packaged", "static-site"]
    said = "\n".join(prompter.said)
    assert "gone → https://github.com/me/gone" in said
    assert "never-cloned" in said and "brand-guide.pdf" in said
    assert support.tree_mtimes(estate) == before, "setup wrote into a discovered repository"
    names = [c.name for c in doctor.run_checks() if c.status == doctor.FAIL]
    assert names == []


def test_cancel_writes_nothing(estate: Path):
    assert setup.run(argparse.Namespace(),
                     ScriptedPrompter(sheet(estate, **{"setup.review": "3"}))) == 1

    assert not paths.hub().exists()
    assert registry.list_projects() == []


def test_a_project_can_be_left_out_at_review(estate: Path):
    prompter = ScriptedPrompter(sheet(estate, **{
        "setup.review": ("2", "1"), "setup.review.project": "4",     # gone
        "setup.review.profile": "4",                                  # do not register
    }))

    setup.run(argparse.Namespace(), prompter)

    assert "gone" not in {entry["name"] for entry in registry.list_projects()}


def test_an_identical_hub_brand_is_used_without_asking(estate: Path):
    brands.write("harbour", {"--color-primary": "#1b365d", "--color-accent": "#C8A45C"}, "Ours.")
    answers = sheet(estate)
    del answers["setup.brand.alpha"]

    setup.run(argparse.Namespace(), ScriptedPrompter(answers))

    assert registry.get_project(estate / "alpha")["brand"] == "harbour"
    assert brands.list_brands() == ["harbour", "reef"]


def test_a_second_run_finds_nothing_new_to_register(estate: Path):
    setup.run(argparse.Namespace(), ScriptedPrompter(sheet(estate)))
    prompter = ScriptedPrompter({"setup.billing": "", "setup.host": "",
                                 "setup.roots": str(estate), "setup.language.code": "",
                                 "setup.language.ui": "", "setup.language.commits": "",
                                 "setup.review": "1"})

    assert setup.run(argparse.Namespace(), prompter) == 0
    assert any("Found 0 projects" in line for line in prompter.said)


def test_discover_reports_new_moved_and_gone_and_writes_nothing(estate: Path):
    setup.run(argparse.Namespace(), ScriptedPrompter(sheet(estate)))
    (estate / "beta").rename(estate / "elsewhere")
    moved = support.make_repo(estate / "moved-here" / "beta", {"a.txt": "x\n"})
    support.make_repo(estate / "fresh", {"index.html": "<!doctype html>\n"})
    prompter = ScriptedPrompter({})

    assert project_command.discover(argparse.Namespace(roots=[str(estate)]), prompter) == 0

    report = prompter.said[-1]
    assert "New: fresh" in report
    assert f"Moved: beta is now at {moved.resolve()}" in report
    assert "`taller setup` registers" in report
