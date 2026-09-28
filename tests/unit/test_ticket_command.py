"""`taller ticket …` — the commands, in plain words, over tickets.py."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

import support
from taller import cli, discovery, registry, tickets
from taller.prompter import ScriptedPrompter


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    return support.new_project()


def run(project: Path, argv: list[str], answers: dict | None = None) -> ScriptedPrompter:
    prompter = ScriptedPrompter(answers or {})
    code = cli.main(["ticket", *argv, "--path", str(project)], prompter)
    assert code == 0, "\n".join(prompter.said)
    prompter.assert_all_used()
    return prompter


def said(prompter: ScriptedPrompter) -> str:
    return "\n".join(prompter.said)


def test_new_asks_for_the_words_the_kind_and_a_title(project: Path):
    prompter = run(project, ["new"], {
        "ticket.words": ["The warning uses a different red.", "It should match the app."],
        "ticket.kind": "1",                              # something broken
        "ticket.title": "",                              # keep the proposal
    })

    ticket = tickets.load(project, 1)
    assert (ticket["kind"], ticket["title"]) == ("bug", "The warning uses a different red")
    body = tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/ticket.md").decode()
    assert "It should match the app." in body
    assert "Created ticket 0001" in said(prompter)
    assert "taller ticket transition 1" in said(prompter)


def test_new_takes_the_words_from_the_command_line(project: Path):
    run(project, ["new", "Add", "an", "export", "button"],
        {"ticket.kind": "2", "ticket.title": "Export button"})

    assert tickets.load(project, 1)["title"] == "Export button"


def test_from_queue_makes_one_ticket_per_entry_and_empties_the_queue(project: Path):
    prompter = run(project, ["new", "--from-queue"])

    found, _ = tickets.list_tickets(project)
    assert [t["title"] for t in found] == support.ANSWERS["first_version"]
    assert all(t["kind"] == "feature" for t in found)
    queue = yaml.safe_load(tickets.read_main(project, ".taller/queue.yml"))
    assert queue["proposed"] == []
    assert "3 tickets" in said(prompter)

    again = run(project, ["new", "--from-queue"])
    assert "queue is empty" in said(again)


def test_from_queue_after_an_interruption_does_not_duplicate(project: Path):
    tickets.create(project, title=support.ANSWERS["first_version"][0], words="w",
                   kind="feature")                   # as if the last run died after one

    run(project, ["new", "--from-queue"])

    titles = [t["title"] for t in tickets.list_tickets(project)[0]]
    assert titles == support.ANSWERS["first_version"]


def test_list_shows_open_tickets_and_marks_blocked(project: Path):
    first = tickets.create(project, title="First", words="w", kind="idea")
    second = tickets.create(project, title="Second", words="w", kind="idea")
    tickets.block(project, second["id"], "waiting for the owner")
    tickets.close(project, first["id"], abandon_reason="dropped")

    text = said(run(project, ["list"]))
    assert "0002" in text and "blocked" in text and "0001" not in text
    assert "0001" in said(run(project, ["list", "--all"]))


def test_show_says_what_comes_next(project: Path):
    tickets.create(project, title="First", words="w", kind="idea")

    text = said(run(project, ["show", "1"]))

    assert "① intake" in text and "taller ticket transition 1" in text
    assert "created at ① intake" in text


def test_transition_asks_for_the_lane_at_triage(project: Path):
    tickets.create(project, title="First", words="w", kind="bug")
    run(project, ["transition", "1"])

    prompter = run(project, ["transition", "1"], {"ticket.lane": "1"})

    ticket = tickets.load(project, 1)
    assert (ticket["lane"], ticket["stage"]) == ("fast", "build")
    assert "④ build" in said(prompter)


def test_approve_reject_resume_and_close(project: Path):
    tickets.create(project, title="First", words="w", kind="feature")
    run(project, ["transition", "1"])
    run(project, ["transition", "1", "--lane", "full"])     # at design

    run(project, ["reject", "1"], {"ticket.reason": "Plan misses the export."})
    assert tickets.load(project, 1)["blocked"]
    assert "unblocked" in said(run(project, ["resume", "1"])).lower()
    run(project, ["approve", "1"])
    assert tickets.load(project, 1)["stage"] == "build"

    run(project, ["close", "1", "--abandon", "Not needed."])
    assert tickets.load(project, 1)["outcome"] == "abandoned"


def test_a_refused_move_is_a_message_not_a_traceback(project: Path):
    tickets.create(project, title="First", words="w", kind="idea")
    prompter = ScriptedPrompter({})

    code = cli.main(["ticket", "approve", "1", "--path", str(project)], prompter)

    assert code == 2 and "not a checkpoint" in prompter.said[-1]


@pytest.mark.parametrize("argv", [["new", "--from-queue"], ["list"], ["show", "1"],
                                  ["transition", "1"], ["resume", "1"]])
def test_every_ticket_command_refuses_an_unadopted_project(tmp_home: Path, identity, argv):
    repo = support.make_repo(tmp_home / "projects" / "found", {"a.txt": "x\n"})
    registry.add_project(path=repo, name="found", profile="flask-sqlite", brand=None,
                         adopted=False)
    prompter = ScriptedPrompter({})

    code = cli.main(["ticket", *argv, "--path", str(repo)], prompter)

    assert code == 2 and "taller project adopt" in prompter.said[-1]
