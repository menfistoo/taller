"""A notice counts only when the job's own record shows it was added (proved live).

Live, 2026-10-03: told only "use your one tool", a notice job could not find its
Todoist tool by that description, reached for another, and then answered
`added: true` with nothing added. So the notifier is told the tool's exact name,
and Taller believes the record, not the answer: sent means the job's transcript
shows that very tool called and answered without error.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import support
from taller import connections, discovery, inference, notify, spend, tickets

LISTING = "claude.ai Todoist: https://tasks.example.test/mcp - ✔ Connected\n"
TOOL = "mcp__claude_ai_Todoist__add-tasks"


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    monkeypatch.setattr(connections, "WORK_USE_READY", True)
    monkeypatch.setattr(connections, "_run_list",
                        lambda: subprocess.CompletedProcess(["claude"], 0, LISTING, ""))
    connections.forget()
    connections.tools_file("todoist").parent.mkdir(parents=True, exist_ok=True)
    connections.tools_file("todoist").write_text(
        json.dumps({"tools": ["add-tasks", "find-tasks"]}), encoding="utf-8")
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", json.dumps(
        {"type": "result", "subtype": "success", "is_error": False, "result": "",
         "session_id": "s-1", "structured_output": {"added": True}}))
    notify.choose("todoist", ["needs_you", "stopped"])
    return support.new_project()


def at_review(project: Path) -> dict:
    made = tickets.create(project, title="A thing", words="Do it.", kind="bug")
    ticket = tickets.load(project, int(made["id"]))
    ticket["stage"] = "review"
    return tickets.write(project, ticket, "ticket 0001: at review")


def transcript(tmp_path: Path, monkeypatch, lines: list[dict]) -> None:
    root = tmp_path / "transcripts"
    folder = root / spend.transcript_slug(notify._cwd())
    folder.mkdir(parents=True)
    (folder / "s-1.jsonl").write_text("\n".join(json.dumps(line) for line in lines),
                                      encoding="utf-8")
    monkeypatch.setattr(spend, "TRANSCRIPTS_ROOT", root)


def used(tool: str, error: bool = False) -> list[dict]:
    return [{"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": tool, "input": {}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": error,
                 "content": "ok"}]}}]


def test_the_notifier_is_told_its_tool_by_name(project, stub_claude, tmp_path, monkeypatch):
    transcript(tmp_path, monkeypatch, used(TOOL))
    prompts = tmp_path / "stdin.jsonl"
    monkeypatch.setenv("STUB_CLAUDE_STDIN", str(prompts))

    notify.tell("toolshed", at_review(project), "needs_you")

    call = [c for c in stub_claude.calls() if "-p" in c][-1]
    assert call[call.index("--allowedTools") + 1] == TOOL
    sent = json.loads(prompts.read_text(encoding="utf-8").splitlines()[-1])
    assert sent["role"] == "notifier" and TOOL in sent["stdin"]


def test_an_answer_of_added_without_the_tool_in_the_record_is_not_believed(
        project, tmp_path, monkeypatch):
    transcript(tmp_path, monkeypatch, used("TaskCreate"))

    told = notify.tell("toolshed", at_review(project), "needs_you")

    assert told == {"sent": False, "problem": notify.NOT_ADDED}


def test_a_tool_that_answered_with_an_error_is_not_a_notice(project, tmp_path, monkeypatch):
    transcript(tmp_path, monkeypatch, used(TOOL, error=True))

    assert notify.tell("toolshed", at_review(project), "needs_you")["sent"] is False


def test_the_record_showing_the_tool_added_it_is_a_notice(project, tmp_path, monkeypatch):
    transcript(tmp_path, monkeypatch, used(TOOL))

    assert notify.tell("toolshed", at_review(project), "needs_you") == \
        {"sent": True, "problem": ""}


def test_no_record_at_all_is_not_a_notice(project, tmp_path, monkeypatch):
    monkeypatch.setattr(spend, "TRANSCRIPTS_ROOT", tmp_path / "nowhere")

    assert notify.tell("toolshed", at_review(project), "needs_you")["sent"] is False


def test_claude_code_s_own_task_tools_are_refused_too():
    assert {"TaskCreate", "TaskUpdate", "TaskList"} <= set(inference.BUILT_IN_TOOLS)
