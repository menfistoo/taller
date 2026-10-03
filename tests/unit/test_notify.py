"""Telling her when something needs her (phase G2, Task 8).

Off until she chooses: a task in her Todoist, or a note on her calendar - notes to
herself, never a message to anyone. When a piece of work stops for her, one
small `notifier` job is allowed exactly one tool of that service, with words
Taller fixes. The same moment is never told twice, and a notice that fails is
recorded and shown; it never blocks, retries or delays the work.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import support
from taller import chief, connections, discovery, hub, notify, tickets
from taller.prompter import ScriptedPrompter

LISTING = """claude.ai Todoist: https://tasks.example.test/mcp - ✔ Connected
claude.ai Google Calendar: https://calendar.example.test/mcp - ✔ Connected
"""



@pytest.fixture(autouse=True)
def work_use_ready(monkeypatch):
    """What is under the switch (connections.WORK_USE_READY), switched on."""
    monkeypatch.setattr(connections, "WORK_USE_READY", True)

@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    monkeypatch.setattr(connections, "_run_list",
                        lambda: subprocess.CompletedProcess(["claude"], 0, LISTING, ""))
    connections.forget()
    # A notifier that answers it added the note.
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", json.dumps(
        {"type": "result", "subtype": "success", "is_error": False, "result": "",
         "session_id": "n", "structured_output": {"added": True}}))
    for service, names in {"todoist": ["add_tasks", "find_tasks", "delete_object"],
                           "google_calendar": ["create_event", "list_events"]}.items():
        connections.tools_file(service).parent.mkdir(parents=True, exist_ok=True)
        connections.tools_file(service).write_text(json.dumps({"tools": names}),
                                                   encoding="utf-8")
    return support.new_project()


def at_review(project: Path) -> dict:
    made = tickets.create(project, title="The loans list doesn't match", words="It is wrong.",
                          kind="bug")
    ticket = tickets.load(project, int(made["id"]))
    ticket["stage"] = "review"
    return tickets.write(project, ticket, "ticket 0001: at review")


def dispatched(stub_claude) -> list[list[str]]:
    return [call for call in stub_claude.calls() if "-p" in call]


def test_off_by_default(project, stub_claude):
    ticket = at_review(project)

    assert notify.configured() == {"channel": None, "when": ["needs_you", "stopped"]}
    assert notify.tell("toolshed", ticket, "needs_you") == {"sent": False, "problem": ""}
    assert dispatched(stub_claude) == []


def test_a_needs_you_moment_sends_one_notice(project, stub_claude):
    notify.choose("todoist", ["needs_you", "stopped"])
    ticket = at_review(project)

    told = notify.tell("toolshed", ticket, "needs_you")

    assert told == {"sent": True, "problem": ""}
    assert len(dispatched(stub_claude)) == 1
    assert tickets.load(project, 1)["notified"]


def test_the_same_moment_is_never_told_twice(project, stub_claude):
    notify.choose("todoist", ["needs_you", "stopped"])
    ticket = at_review(project)

    notify.tell("toolshed", ticket, "needs_you")
    notify.tell("toolshed", tickets.load(project, 1), "needs_you")

    assert len(dispatched(stub_claude)) == 1


def test_the_notifier_is_allowed_one_tool_only(project, stub_claude):
    notify.choose("todoist", ["needs_you", "stopped"])

    notify.tell("toolshed", at_review(project), "needs_you")

    call = dispatched(stub_claude)[0]
    assert call[call.index("--allowedTools") + 1] == "mcp__todoist__add_tasks"
    given = json.loads(call[call.index("--mcp-config") + 1])["mcpServers"]
    assert list(given) == ["todoist"]


def test_a_calendar_note_uses_the_calendar(project, stub_claude):
    notify.choose("calendar", ["needs_you"])

    notify.tell("toolshed", at_review(project), "needs_you")

    call = dispatched(stub_claude)[0]
    assert call[call.index("--allowedTools") + 1] == "mcp__google_calendar__create_event"


def test_only_the_moments_she_ticked_are_told(project, stub_claude):
    notify.choose("todoist", ["stopped"])

    told = notify.tell("toolshed", at_review(project), "needs_you")

    assert told["sent"] is False and dispatched(stub_claude) == []


def test_a_failed_notice_is_recorded_and_the_work_carries_on(project, stub_claude,
                                                             monkeypatch):
    notify.choose("todoist", ["needs_you", "stopped"])
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", json.dumps(
        {"type": "result", "subtype": "error", "is_error": True, "result": "signed out"}))
    monkeypatch.setenv("STUB_CLAUDE_EXIT", "1")

    told = notify.tell("toolshed", at_review(project), "needs_you")

    assert told["sent"] is False and told["problem"]
    assert notify.last_problem() == told["problem"]
    assert len(dispatched(stub_claude)) == 1, "no retry against her account"


def test_a_notice_says_what_and_where_in_her_words(project):
    ticket = at_review(project)

    said = notify.notice("toolshed", ticket, "needs_you")

    assert said.startswith('toolshed: "The loans list doesn\'t match" is ready for you to look at.')
    assert "/thing/toolshed/1" in said


def test_the_chief_tells_her_when_it_stops_for_her(project, stub_claude, monkeypatch,
                                                    tmp_path):
    told: list[tuple[str, str]] = []
    monkeypatch.setattr(notify, "tell",
                        lambda name, ticket, why: told.append((name, why)) or {})
    from taller import cli
    assert cli.main(["models", "probe"], ScriptedPrompter({})) == 0
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"chief": [{"value": {"kind": "bug", "title": "Heading",
                                                       "summary": "The heading."}}],
                                  "explorer": [{"fail": "no"}, {"fail": "no"}]}),
                      encoding="utf-8")
    monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(script))
    made = tickets.create(project, title="x", words="The heading.", kind="feature",
                          named_by=None)

    chief.run(project, int(made["id"]), say=lambda _: None)

    assert told == [("toolshed", "stopped")]


def page_text(client, where: str = "/services") -> str:
    import html, re
    raw = re.sub(r"(?s)<(style|script).*?</>", " ", client.get(where).get_data(as_text=True))
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw)).split())


def form_token(client) -> dict[str, str]:
    import cockpit
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def test_the_services_page_offers_to_tell_her_and_keeps_her_choice(project):
    import cockpit
    from cockpit import words
    client = cockpit.create_app(testing=True).test_client()

    page = page_text(client)
    assert "Tell me when something needs me" in page
    assert "Add a task to my Todoist" in page and "Put a note on my calendar" in page
    assert words.SERVICES["notify_never"] in page

    client.post("/services/notify", follow_redirects=True,
                data={**form_token(client), "channel": "todoist", "when": "needs_you"})

    assert notify.configured() == {"channel": "todoist", "when": ["needs_you"]}


def test_a_failed_notice_shows_on_the_services_page(project, stub_claude, monkeypatch):
    import cockpit
    notify.choose("todoist", ["needs_you"])
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", json.dumps(
        {"type": "result", "subtype": "error", "is_error": True, "result": "signed out"}))
    monkeypatch.setenv("STUB_CLAUDE_EXIT", "1")
    told = notify.tell("toolshed", at_review(project), "needs_you")

    client = cockpit.create_app(testing=True).test_client()

    assert told["problem"] in page_text(client)
