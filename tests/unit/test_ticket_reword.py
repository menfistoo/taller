"""Changing what was asked for, while changing it still means something (spec 12).

The third action on a ticket, beside approve and reject. It is her own words
being corrected, so it is written to `main` like the words were - and it is
refused once there is a branch and a plan built on the old ones, because §7.2
already has a way to send those back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import support
from taller import discovery, tickets
from taller.errors import ConfigError


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    path = support.new_project()
    tickets.create(path, title="Heading colour", words="The red is wrong.", kind="bug")
    return path


def notes_of(project: Path, ticket: dict) -> str:
    raw = tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/notes.md") or b""
    return raw.decode("utf-8")


def test_the_ask_can_be_changed_before_the_work_starts(project):
    changed = tickets.reword(project, 1, title="The heading colour",
                             words="Use the brand's own red, not a literal.")

    assert changed["title"] == "The heading colour"
    assert tickets._words(project, changed).strip() == \
        "Use the brand's own red, not a literal."
    assert "changed what was asked for" in notes_of(project, changed)


def test_the_folder_does_not_move_when_the_title_changes(project):
    before = tickets.ticket_dir(tickets.load(project, 1))

    changed = tickets.reword(project, 1, title="Something else entirely",
                             words="The red is wrong.")

    assert tickets.ticket_dir(changed) == before
    assert tickets.read_main(project, f"{before}/ticket.md")


def test_changing_the_ask_at_design_is_still_allowed(project):
    ticket = tickets.load(project, 1)
    ticket.update({"stage": "design", "lane": "full"})
    tickets.write(project, ticket, "ticket 0001: at design")

    changed = tickets.reword(project, 1, title="Heading colour", words="Use the token.")

    assert tickets._words(project, changed).strip() == "Use the token."


def test_changing_the_ask_after_design_is_refused(project):
    ticket = tickets.load(project, 1)
    ticket.update({"stage": "build", "lane": "fast", "branch": "ticket/0001-heading-colour"})
    tickets.write(project, ticket, "ticket 0001: at build")

    with pytest.raises(ConfigError) as refused:
        tickets.reword(project, 1, title="Heading colour", words="Something else.")

    assert "reject" in str(refused.value)
    assert tickets._words(project, tickets.load(project, 1)).strip() == "The red is wrong."


def test_an_empty_ask_is_refused(project):
    with pytest.raises(ConfigError):
        tickets.reword(project, 1, title="Heading colour", words="   ")
    with pytest.raises(ConfigError):
        tickets.reword(project, 1, title="  ", words="The red is wrong.")


def test_a_blocked_ticket_is_not_reworded_behind_the_block(project):
    tickets.block(project, 1, "the explorer gave no usable answer twice")

    with pytest.raises(ConfigError):
        tickets.reword(project, 1, title="Heading colour", words="Try again.")


def test_rewording_does_not_file_an_issue_with_the_old_words(project, monkeypatch):
    """The deferred GitHub issue is built from what `main` holds, and during a
    reword `main` still holds the OLD words - so filing it here would open an
    issue whose title and body disagree."""
    from taller import discovery, issues

    asked: list[list[str]] = []
    monkeypatch.setattr(issues, "repo_of", lambda path: "menfistoo/toolshed")
    monkeypatch.setattr(discovery, "_run_gh",
                        lambda args, **kwargs: asked.append(list(args)) or None)

    tickets.reword(project, 1, title="The heading colour",
                   words="Use the brand's own red.")

    filed = [argv for argv in asked if argv[:2] == ["issue", "create"]]
    assert not filed, f"an issue was filed while main still held the old words: {filed}"
