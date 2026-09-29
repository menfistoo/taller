"""Every question Taller asks can be answered from a file (plugin plan, Task 1).

A chat has no keyboard for Taller's prompts. With `--answers`, or whenever stdin
is not a terminal, a question the file does not answer ends the command with
`NEEDS <id>` and exit 3 - never a hang, never a silent cancel. Running the same
command again with the answer must not repeat what the first run already did.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import support
from taller import cli, discovery, onboarding, paths, registry, tickets
from taller.commands import brand as brand_command
from taller.prompter import AnswerSheetPrompter, NeedsAnswer

NEW_PROJECT = {
    "setup.billing": "", "setup.host": "", "setup.language.code": "en",
    "setup.language.ui": "es", "setup.language.commits": "en",
    "q1": "Tracks which neighbour has borrowed which tool.", "q2": "A marketplace.",
    "q3": "Who has which tool.", "q4": "1", "q5": "", "q6": "", "q7": "Tools and loans.",
    "q8": "n", "q9": "1", "q10": "1", "q11": "", "q12": ["List the tools"], "brief": "1",
}
CLASSIFY = {"value": {"kind": "bug", "title": "Heading colour",
                      "summary": "The heading should use the danger colour."}}


@pytest.fixture
def home(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(brand_command, "open_in_browser", lambda page: None)
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    return tmp_home


@pytest.fixture
def sheet(tmp_path: Path):
    path = tmp_path / "answers.json"

    def write(answers: dict) -> str:
        path.write_text(json.dumps(answers), encoding="utf-8")
        return str(path)
    return write


def script(tmp_path: Path, monkeypatch, **answers) -> None:
    path = tmp_path / "script.json"
    path.write_text(json.dumps(answers), encoding="utf-8")
    monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(path))


def test_the_prompter_raises_needs_for_an_unanswered_question():
    prompter = AnswerSheetPrompter({"a": "yes"})

    assert prompter.ask("a", "First?") == "yes"
    with pytest.raises(NeedsAnswer) as caught:
        prompter.ask("a", "First, again?")
    assert (caught.value.qid, caught.value.prompt) == ("a", "First, again?")
    assert prompter.interactive is False


def test_a_missing_answer_stops_with_needs_and_its_own_exit_code(home, sheet, capsys):
    project = support.new_project()

    code = cli.main(["--answers", sheet({}), "ticket", "new", "--path", str(project)])

    out = capsys.readouterr().out
    assert code == cli.EXIT_NEEDS_ANSWER == 3
    assert out.lstrip().startswith("NEEDS ticket.words")
    assert "What should be done?" in out and '"ticket.words"' in out
    assert tickets.list_tickets(project)[0] == []


def test_the_answer_from_the_file_is_used(home, sheet, tmp_path, monkeypatch):
    project = support.new_project()
    script(tmp_path, monkeypatch, chief=[CLASSIFY])

    code = cli.main(["--answers", sheet({"ticket.words": ["The heading red is wrong."]}),
                     "ticket", "new", "--path", str(project)])

    assert code == 0
    assert tickets.load(project, 1)["kind"] == "bug"


def test_inside_a_chat_taller_asks_for_answers_instead_of_hanging(home, monkeypatch,
                                                                   capsys):
    project = support.new_project()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setenv("CLAUDECODE", "1")                  # a Claude Code chat's shell

    code = cli.main(["ticket", "new", "--path", str(project)])

    assert code == 3 and "NEEDS ticket.words" in capsys.readouterr().out


def test_an_invalid_answer_explains_then_needs_it_again(home, sheet, capsys):
    projects = paths.home() / "projects"

    code = cli.main(["--answers", sheet({**NEW_PROJECT, "q4": "7"}), "project", "new",
                     "toolshed", "--path", str(projects), "--no-open"])

    out = capsys.readouterr().out
    assert code == 3
    assert out.index("Please choose a number") < out.index("NEEDS q4")


def test_project_new_completes_from_a_full_sheet_and_resumes_after_needs(home, sheet,
                                                                         capsys):
    projects = paths.home() / "projects"
    argv = ["project", "new", "toolshed", "--path", str(projects), "--no-open"]
    partial = {k: v for k, v in NEW_PROJECT.items() if k not in ("q7", "q8", "q9", "q10",
                                                                  "q11", "q12", "brief")}

    first = cli.main(["--answers", sheet(partial), *argv])
    assert first == 3 and "NEEDS q7" in capsys.readouterr().out
    second = cli.main(["--answers", sheet({**NEW_PROJECT, "resume": "y"}), *argv])

    assert second == 0, capsys.readouterr().out
    assert [e["name"] for e in registry.list_projects()] == ["toolshed"]
    assert onboarding.load_progress("toolshed") in (None, {})


def test_a_new_ticket_the_chief_cannot_name_is_left_for_intake_not_asked(
        home, sheet, tmp_path, monkeypatch, capsys):
    project = support.new_project()
    monkeypatch.setenv("STUB_CLAUDE_FAIL_EXIT", "1")

    code = cli.main(["--answers", sheet({}), "ticket", "new", "The", "red", "is", "wrong",
                     "--path", str(project)])

    out = capsys.readouterr().out
    assert code == 0, out
    listed, _ = tickets.list_tickets(project)
    assert len(listed) == 1 and listed[0]["named_by"] is None
    assert "when it runs" in out and "NEEDS" not in out
