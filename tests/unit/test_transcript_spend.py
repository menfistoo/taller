"""What a chat spent on a ticket's branch, read from Claude Code's transcripts.

Spec 7.5: `Result.usage` is authoritative for Taller's own dispatches; the
transcript is the fallback for work Taller did not dispatch. Two things must
never be counted twice - one message written as several lines, and Taller's own
`claude -p` dispatches, whose transcripts sit in the same folders. Plugin plan,
Task 4.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import support
from taller import cli, config, discovery, inference, spend, tickets
from taller.prompter import ScriptedPrompter

MODEL = "claude-opus-5-5"


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    return support.new_project()


def ticket_on_branch(project: Path) -> dict:
    ticket = tickets.create(project, title="Heading", words="x", kind="bug")
    ticket["branch"] = "ticket/0001-heading"
    ticket["spend"] = {**ticket["spend"], "sessions": ["dispatch-1"]}
    return tickets.write(project, ticket, "ticket 0001: branch")


def record(session: str, branch: str, message_id: str, *, input_: int = 10,
           output: int = 40, kind: str = "assistant") -> str:
    return json.dumps({
        "type": kind, "sessionId": session, "gitBranch": branch,
        "timestamp": "2026-09-28T10:00:00Z",
        "message": {"id": message_id, "model": MODEL, "role": "assistant",
                    "usage": {"input_tokens": input_, "cache_creation_input_tokens": 20,
                              "cache_read_input_tokens": 30, "output_tokens": output}}})


def write_transcript(root: Path, where: Path, name: str, *lines: str) -> None:
    folder = root / spend.transcript_slug(where)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_the_slug_matches_claude_codes():
    assert spend.transcript_slug(Path(r"C:\Users\x\proj")) == "C--Users-x-proj"
    assert spend.transcript_slug(Path("/home/x/my.proj")) == "-home-x-my-proj"


def test_a_dispatch_records_its_session(project):
    ticket = tickets.create(project, title="t", words="x", kind="bug")
    result = inference.Result(ok=True, session_id="abc", usage=[
        inference.UsageRecord(model=MODEL, input=1, cache_write=0, cache_read=0, output=1)])

    spend.fold(project, ticket["id"], result, config.load_hub_config())
    spend.fold(project, ticket["id"], result, config.load_hub_config())

    assert tickets.load(project, ticket["id"])["spend"]["sessions"] == ["abc"]


def test_chat_spend_on_the_branch_is_counted_once_per_message(project, tmp_path):
    ticket = ticket_on_branch(project)
    branch = ticket["branch"]
    write_transcript(tmp_path, project, "chat",
                     record("chat", branch, "m1"), record("chat", branch, "m1"),
                     record("chat", branch, "m2", input_=5, output=5))

    found = spend.from_transcripts(project, ticket, root=tmp_path)

    assert found == {MODEL: {"input": 15, "cache_write": 40, "cache_read": 60,
                             "output": 45}}


def test_taller_s_own_dispatches_are_not_counted_twice(project, tmp_path, monkeypatch):
    ticket = ticket_on_branch(project)
    # A short stand-in: the real worktree path's transcript folder would pass
    # Windows' 260-character path limit under a pytest temporary directory.
    worktree = Path(r"C:\wt\toolshed-0001")
    monkeypatch.setattr(tickets, "_worktree", lambda project, ticket: worktree)
    write_transcript(tmp_path, worktree, "dispatch-1",
                     record("dispatch-1", ticket["branch"], "d1"))
    write_transcript(tmp_path, worktree, "chat-in-worktree",
                     record("chat-in-worktree", ticket["branch"], "w1"))

    found = spend.from_transcripts(project, ticket, root=tmp_path)

    assert found[MODEL]["output"] == 40                       # w1 only


def test_other_branches_and_garbled_lines_are_ignored(project, tmp_path):
    ticket = ticket_on_branch(project)
    write_transcript(tmp_path, project, "chat",
                     record("chat", "main", "m1"), "{not json",
                     record("chat", ticket["branch"], "u1", kind="user"),
                     json.dumps({"type": "assistant", "gitBranch": ticket["branch"]}))

    assert spend.from_transcripts(project, ticket, root=tmp_path) == {}


def test_ticket_show_reports_chat_spend(project, tmp_path, monkeypatch):
    ticket = ticket_on_branch(project)
    write_transcript(tmp_path, project, "chat", record("chat", ticket["branch"], "m1"))
    monkeypatch.setattr(spend, "TRANSCRIPTS_ROOT", tmp_path)
    prompter = ScriptedPrompter({})

    assert cli.main(["ticket", "show", "1", "--path", str(project)], prompter) == 0

    said = "\n".join(prompter.said)
    assert "In a chat:" in said and "weighted tokens" in said
