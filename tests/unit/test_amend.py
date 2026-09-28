"""`taller amend`: a rule change is committed and everything it reaches refreshed.

Spec 4.6 (an amend to a shared module writes to every project using it, and
says which), 9.8 (amendment, not argument). Plugin plan, Task 2.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import support
from taller import cli, discovery, paths, tickets
from taller.prompter import ScriptedPrompter


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def snapshot_sha(project: Path) -> str:
    return json.loads(tickets.read_main(project, ".taller/resolved.json"))["hub_sha"]


@pytest.fixture
def two(tmp_home: Path, identity, stub_claude, monkeypatch) -> list[Path]:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    monkeypatch.chdir(tmp_home)                 # not standing in any project
    return [support.new_project("toolshed"), support.new_project("seed-bank")]


def amend(*argv: str) -> tuple[int, str]:
    prompter = ScriptedPrompter({})
    code = cli.main(["amend", *argv], prompter)
    return code, "\n".join(prompter.said)


def test_amending_a_hub_module_refreshes_every_project_that_uses_it(two):
    module = paths.hub() / "modules" / "never.md"
    module.write_text(module.read_text(encoding="utf-8") + "\n- No inline styles.\n",
                      encoding="utf-8", newline="")

    code, said = amend("--reason", "No inline styles")

    assert code == 0, said
    hub_head = git(paths.hub(), "log", "-1", "--format=%H %s").split(" ", 1)
    assert hub_head[1].strip() == "amend: No inline styles"
    assert [snapshot_sha(p) for p in two] == [hub_head[0]] * 2
    assert "toolshed" in said and "seed-bank" in said


def test_amending_a_project_slice_commits_it_and_refreshes_that_project(two):
    project = two[0]
    slice_ = project / ".taller" / "constitution" / "never.md"
    slice_.write_text(slice_.read_text(encoding="utf-8") + "\n- Never delete a loan.\n",
                      encoding="utf-8", newline="")

    code, said = amend("--reason", "Loans are history", "--path", str(project))

    assert code == 0, said
    assert "amend: Loans are history" in git(project, "log", "--format=%s", "-5")
    assert git(project, "status", "--porcelain") == ""
    assert "Never delete a loan" in git(project, "show", "main:.taller/constitution/never.md")
    assert "toolshed" in said


def test_a_project_amend_off_main_is_refused(two):
    project = two[0]
    git(project, "checkout", "-q", "-b", "elsewhere")
    slice_ = project / ".taller" / "constitution" / "never.md"
    slice_.write_text("changed\n", encoding="utf-8")

    code, said = amend("--reason", "x", "--path", str(project))

    assert code == cli.EXIT_REFUSED and "main" in said
    assert "amend: x" not in git(project, "log", "--format=%s", "-3")


def test_nothing_pending_says_so(two):
    code, said = amend("--reason", "nothing")

    assert code == 0 and "Nothing to amend" in said


def test_the_reason_is_required(two, tmp_path, capsys):
    module = paths.hub() / "modules" / "never.md"
    module.write_text(module.read_text(encoding="utf-8") + "\n- x\n", encoding="utf-8")
    answers = tmp_path / "a.json"
    answers.write_text("{}", encoding="utf-8")

    code = cli.main(["--answers", str(answers), "amend"])

    assert code == cli.EXIT_NEEDS_ANSWER and "NEEDS amend.reason" in capsys.readouterr().out
