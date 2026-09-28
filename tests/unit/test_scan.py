"""`taller scan`: the whole tree through every model-free gate - Health's figures.

Spec 9.5, 12, criterion 15. Smoke is exempt; nothing is written.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import support
from taller import cli, registry
from taller.commands import scan
from taller.prompter import ScriptedPrompter

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "broken-app"
RULESET = {
    "hub_sha": "a" * 40, "language": {"code": "en", "ui": "es"}, "non_suppressible": [],
    "overrides": [],
    "thresholds": {"max_file_lines": 800, "max_function_lines": 80, "dup_block_lines": 12,
                   "min_coverage_pct": 0},
    "paths": {"layers": {"routes/**": ["database", "utils.*"]}, "tests_dir": "tests",
              "brand_tokens": "static/css/tokens.css"},
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def test_scan_reports_the_broken_apps_violations_by_severity(tmp_path: Path, identity):
    repo = tmp_path / "broken-app"
    shutil.copytree(FIXTURE, repo)
    support.make_repo(repo, {})
    git(repo, "add", "--all")

    health = scan.health(repo, RULESET)

    assert health["counts"]["high"] == 5           # 3 colours, 1 font, 1 layer
    assert health["counts"]["medium"] == 3         # root md, fix_thing.py, a long function
    assert health["counts"]["low"] == 1            # the duplicated block
    assert health["top_rules"][0] == ("brand.hardcoded-color", 3)
    assert health["tests"]["tests_run"] == 0 and health["errors"] == []
    assert set(health["gates"]) == {"constitution", "size", "tests"}


def test_the_report_prints_counts_top_rules_and_tests():
    text = scan.render("broken-app", {
        "counts": {"blocker": 0, "high": 5, "medium": 3, "low": 1, "nit": 0},
        "top_rules": [("brand.hardcoded-color", 3), ("brand.hardcoded-font", 1)],
        "tests": {"tests_run": 4, "tests_passed": 3, "duration_s": 1.5},
        "gates": ["constitution", "size", "tests"], "errors": []})

    assert "broken-app" in text
    assert "0 blocker, 5 high, 3 medium, 1 low, 0 nit" in text
    assert "brand.hardcoded-color ×3" in text and "4 run, 3 passed" in text


@pytest.fixture
def two_projects(tmp_home: Path, identity, stub_claude, monkeypatch) -> list[Path]:
    monkeypatch.setattr("taller.discovery._run_gh", lambda args: None)
    return [support.new_project("toolshed"), support.new_project("seed-bank")]


def test_scan_all_covers_every_adopted_project(two_projects):
    prompter = ScriptedPrompter({})

    code = cli.main(["scan", "--all"], prompter)

    said = "\n".join(prompter.said)
    assert code == 0, said
    assert "toolshed" in said and "seed-bank" in said
    assert said.count("tests:") == 2


def test_scan_writes_nothing(two_projects):
    project = two_projects[0]
    before = (git(project, "rev-parse", "main"), git(project, "status", "--porcelain",
                                                     "--ignored"))

    code = cli.main(["scan", str(project)], ScriptedPrompter({}))

    assert code == 0
    assert (git(project, "rev-parse", "main"),
            git(project, "status", "--porcelain", "--ignored")) == before
    assert registry.get_project(project)["name"] == "toolshed"
