"""`taller project brief` and `show` — answers reopened, changes as one amendment."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest
import yaml

import support
from taller import doctor, paths, registry, scaffold
from taller.commands import project as project_command
from taller.errors import ConfigError, GitError
from taller.prompter import ScriptedPrompter

ANSWERS = {
    "what_it_does": "Tracks which neighbour has borrowed which shared tool.",
    "what_it_is_not": "A marketplace.", "must_never_break": "Who has which tool.",
    "users": "team", "reach": "a private network", "phone": True,
    "stores": "Tools and loans.", "sensitive_data": False, "deploy": "local",
    "first_version": ["Record a loan"],
}


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude) -> Path:
    support.write(paths.hub_config(), yaml.safe_dump(
        {"language": {"code": "en", "ui": "es", "commits": "en"}}))
    target = paths.home() / "projects" / "toolshed"
    scaffold.create_project(target, name="toolshed", profile="flask-sqlite",
                            brand=None, answers=ANSWERS)
    return target


def args(project: Path) -> argparse.Namespace:
    return argparse.Namespace(path=str(project), no_open=True)


def log(project: Path) -> list[str]:
    return subprocess.run(["git", "-C", str(project), "log", "--format=%s"],
                          capture_output=True, text=True, encoding="utf-8").stdout.splitlines()


def slice_text(project: Path, name: str) -> str:
    return (paths.project_constitution(project) / f"{name}.md").read_text(encoding="utf-8")


def test_changed_answers_become_one_amendment_and_the_snapshot_follows(project: Path):
    before = log(project)
    prompter = ScriptedPrompter({
        "brief.edit": ("2", "8", ""), "q2": "A marketplace, or a rental service.",
        "q8": "y", "brief.approve": "",
    })

    assert project_command.brief(args(project), prompter) == 0

    prompter.assert_all_used()
    new = log(project)[: len(log(project)) - len(before)]
    assert new[-1] == "amend: brief (② ⑧)"
    assert "or a rental service" in slice_text(project, "never")
    assert "credentials: yes" in slice_text(project, "product")
    assert scaffold.load_brief(project)["sensitive_data"] is True
    failed = [c.name for c in doctor.run_checks() if c.status == doctor.FAIL]
    assert failed == [], "the amendment left the constitution stale"


def test_enter_keeps_an_answer_and_nothing_changed_writes_nothing(project: Path):
    before = log(project)
    prompter = ScriptedPrompter({"brief.edit": ("7", ""), "q7": ""})

    assert project_command.brief(args(project), prompter) == 0

    assert prompter.said[-1] == "Nothing changed."
    assert log(project) == before


def test_the_profile_and_brand_are_not_answer_edits(project: Path):
    prompter = ScriptedPrompter({"brief.edit": ("9", "10", "")})

    project_command.brief(args(project), prompter)

    assert sum("not an answer edit" in line for line in prompter.said) == 2


def test_declining_writes_nothing(project: Path):
    before = log(project)

    code = project_command.brief(args(project), ScriptedPrompter(
        {"brief.edit": ("2", ""), "q2": "Something else.", "brief.approve": "n"}))

    assert code == 1
    assert log(project) == before
    assert subprocess.run(["git", "-C", str(project), "status", "--porcelain"],
                          capture_output=True, text=True).stdout == ""


def test_a_dirty_checkout_is_refused_before_any_question(project: Path):
    (project / "app.py").write_text("# an edit in progress\n", encoding="utf-8")

    with pytest.raises(GitError, match="uncommitted"):
        project_command.brief(args(project), ScriptedPrompter({}))


def test_a_project_on_a_branch_is_refused(project: Path):
    subprocess.run(["git", "-C", str(project), "checkout", "--quiet", "-b", "work"],
                   check=True)

    with pytest.raises(GitError, match="Switch to `main`"):
        project_command.brief(args(project), ScriptedPrompter({}))


def test_a_discovered_project_has_no_brief_yet(tmp_home: Path, project: Path):
    other = paths.home() / "projects" / "found"
    other.mkdir()
    registry.add_project(path=other, name="found", profile="flask-sqlite", brand=None,
                         adopted=False)

    with pytest.raises(ConfigError, match="not adopted"):
        project_command.brief(args(other), ScriptedPrompter({}))


def test_show_prints_the_brief_and_the_queue(project: Path):
    prompter = ScriptedPrompter({})

    assert project_command.show(argparse.Namespace(path=str(project)), prompter) == 0

    text = prompter.said[-1]
    assert "toolshed  (adopted)" in text
    assert "Tracks which neighbour" in text
    assert "Queue: 1 proposed" in text and "Record a loan" in text
