"""`taller hook session-start`: a chat in a Taller project starts out knowing it.

Spec 3.1: in a Claude Code session the briefing arrives through a SessionStart
hook. Plain text on stdout is added to the chat's context. The hook never breaks
a session: anything wrong means no output and exit 0. Plugin plan, Task 3.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

import support
from taller import cli, discovery, paths, tickets
from taller.commands import hook


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    return support.new_project()


def run_hook(monkeypatch, capsys, stdin: str) -> tuple[int, str]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    code = cli.main(["hook", "session-start"])
    return code, capsys.readouterr().out


def test_a_chat_in_a_project_is_told_its_rules_and_open_tickets(project, monkeypatch,
                                                                capsys):
    made = tickets.create(project, title="Heading colour", words="The red is wrong.",
                          kind="bug")
    tickets.block(project, made["id"], "waiting for a decision")
    index = tickets.read_main(project, ".taller/constitution/00-index.md").decode("utf-8")

    code, out = run_hook(monkeypatch, capsys,
                         json.dumps({"cwd": str(project / "static"), "session_id": "s"}))

    assert code == 0
    assert "toolshed" in out and "flask-sqlite" in out
    assert index.strip().splitlines()[-1] in out
    assert "0001" in out and "Heading colour" in out and "blocked" in out
    assert "/taller:status" in out


def test_a_chat_elsewhere_gets_nothing(project, tmp_path, monkeypatch, capsys):
    code, out = run_hook(monkeypatch, capsys, json.dumps({"cwd": str(tmp_path)}))

    assert (code, out) == (0, "")


def test_garbage_on_stdin_starts_the_chat_quietly(project, monkeypatch, capsys):
    assert run_hook(monkeypatch, capsys, "not json") == (0, "")


def test_a_broken_registry_starts_the_chat_quietly(project, monkeypatch, capsys):
    paths.registry().write_text("{broken", encoding="utf-8")

    assert run_hook(monkeypatch, capsys, json.dumps({"cwd": str(project)})) == (0, "")


def test_the_briefing_is_capped(project, monkeypatch):
    for n in range(80):
        tickets.create(project, title=f"Ticket number {n} with a long enough title",
                       words="x", kind="idea")

    text = hook.briefing(project)

    assert 0 < len(text) <= hook.BRIEFING_MAX
