"""`taller project new` — setup when needed, the interview, the brief, the project."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest
import yaml

import support
from taller import discovery, onboarding, paths, registry
from taller.commands import brand as brand_command
from taller.commands import project
from taller.errors import ConfigError
from taller.prompter import ScriptedPrompter

SETUP = {"setup.billing": "", "setup.host": "", "setup.language.code": "en",
         "setup.language.ui": "es", "setup.language.commits": "en"}
SHEET = {
    "q1": "Tracks which neighbour has borrowed which shared tool.",
    "q2": "A marketplace: nothing is bought, sold or rented.",
    "q3": "Knowing who has which tool right now.",
    "q4": "2", "q5": "", "q6": "", "q7": "Tools, neighbours and loans.", "q8": "n",
    "q9": "1", "q10": "1", "q11": "",
    "q12": ["List the tools", "Record a loan", "Show who has what"],
}


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch, identity):
    """No browser, and no `gh` unless a test provides one."""
    monkeypatch.setattr(brand_command, "open_in_browser", lambda page: None)
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)


def args(name: str = "toolshed", **extra) -> argparse.Namespace:
    return argparse.Namespace(name=name, path=str(paths.home() / "projects"),
                              no_open=True, **extra)


def target(name: str = "toolshed") -> Path:
    return paths.home() / "projects" / name


def hub_log() -> list[str]:
    return subprocess.run(["git", "-C", str(paths.hub()), "log", "--format=%s"],
                          capture_output=True, text=True).stdout.splitlines()


def test_on_an_empty_hub_setup_runs_first_then_the_project_is_created(tmp_home: Path):
    prompter = ScriptedPrompter({**SETUP, **SHEET, "brief": "1"})

    assert project.new(args(), prompter) == 0

    prompter.assert_all_used()
    assert registry.get_project(target())["profile"] == "flask-sqlite"
    assert not paths.onboarding("toolshed").exists(), "the resume file outlived the project"
    assert hub_log() == ["project: add toolshed", "setup: connection and languages"]
    report = prompter.said[-1]
    assert "Created toolshed" in report and "not pushed: no remote" in report
    assert "Record a loan" in report


def test_a_configured_hub_goes_straight_to_the_questions(tmp_home: Path):
    support.write(paths.hub_config(), yaml.safe_dump(
        {"language": {"code": "en", "ui": "es", "commits": "en"}}))
    prompter = ScriptedPrompter({**SHEET, "brief": "1"})

    assert project.new(args(), prompter) == 0
    assert not [qid for qid in prompter.asked if qid.startswith("setup.")]


def test_cancel_at_the_brief_creates_nothing_and_keeps_the_answers(tmp_home: Path):
    prompter = ScriptedPrompter({**SETUP, **SHEET, "brief": "3"})

    assert project.new(args(), prompter) == 1

    assert not target().exists()
    assert registry.list_projects() == []
    assert onboarding.load_progress("toolshed")["users"] == "team"
    assert "picks up from here" in prompter.said[-1]


def test_an_answer_can_be_changed_from_the_brief(tmp_home: Path):
    prompter = ScriptedPrompter({**SETUP, **SHEET, "brief": ("2", "1"),
                                 "brief.edit": ("13", "7"), "q7": (SHEET["q7"], "Only tools.")})

    assert project.new(args(), prompter) == 0

    product = (paths.project_constitution(target()) / "product.md").read_text(encoding="utf-8")
    assert "Only tools." in product


def test_a_non_empty_target_is_refused_before_any_question(tmp_home: Path):
    support.write(target() / "precious.txt", "mine\n")

    with pytest.raises(ConfigError, match="not empty"):
        project.new(args(), ScriptedPrompter({}))


def test_a_remote_is_offered_when_gh_can_and_defaults_to_no(tmp_home: Path, monkeypatch):
    calls = []

    def gh(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "✓ Logged in to github.com account me\n"
                                                    "  - Token scopes: 'repo', 'workflow'\n", "")
    monkeypatch.setattr(discovery, "_run_gh", gh)
    prompter = ScriptedPrompter({**SETUP, **SHEET, "brief": "1", "remote": ""})

    assert project.new(args(), prompter) == 0

    assert not [argv for argv in calls if argv[:2] == ["repo", "create"]]
    assert "not pushed" in prompter.said[-1]


def test_the_default_parent_is_beside_the_current_repository(tmp_path: Path, monkeypatch):
    repo = tmp_path / "work" / "existing"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    monkeypatch.chdir(repo)

    assert project.default_parent().resolve() == (tmp_path / "work").resolve()
