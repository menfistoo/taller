"""What the final review of phase G2 found, each pinned by a test.

Letting Taller's work use her services is not proven live yet (her choice: build
it, prove it later), so it ships switched off, and says so. The code under the
switch is still held to what it promises: nothing that sends, shares or invites,
her real services found by their real names, a notice counted only when it
arrived, and only plain sentences on her pages.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import words
from taller import config, connections, constitution, discovery, hub, inference, notify, tickets
from taller.errors import ConfigError

LISTING = """claude.ai Gmail: https://mail.example.test/mcp - ✔ Connected
claude.ai Todoist: https://tasks.example.test/mcp - ✔ Connected
claude.ai Google Calendar: https://calendar.example.test/mcp - ! Needs authentication
plugin:team:gmail:  (HTTP) - - Not configured
plugin:office:gmail:  (HTTP) - - Not configured
"""


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    monkeypatch.setattr(connections, "_run_list",
                        lambda: subprocess.CompletedProcess(["claude"], 0, LISTING, ""))
    connections.forget()
    for service, names in {"gmail": ["search_threads", "send_message"],
                           "todoist": ["add-tasks", "find-tasks", "delete-object"],
                           "google_calendar": ["create_event", "list_events"]}.items():
        connections.tools_file(service).parent.mkdir(parents=True, exist_ok=True)
        connections.tools_file(service).write_text(json.dumps({"tools": names}),
                                                   encoding="utf-8")
    return support.new_project()


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(connections, "WORK_USE_READY", True)


def argv_for(project: Path, role: str = "explorer") -> list[str]:
    dispatch = inference.Dispatch(role=role, prompt="hello", config=config.load_hub_config(),
                                  ruleset=constitution.resolve(project),
                                  tools=inference.role_tools(role))
    return inference._build(dispatch, "claude")[0]


def text_of(answer) -> str:
    raw = re.sub(r"(?s)<(style|script)\b.*?</\1>", " ", answer.get_data(as_text=True))
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw)).split())


# --- I6: not ready, and said so ------------------------------------------------------

def test_letting_work_use_a_service_is_switched_on_once_proved_live(project):
    """Proved on her accounts (2026-10-03): Drive 'May look', and a Todoist notice."""
    client = cockpit.create_app(testing=True).test_client()
    page = text_of(client.get("/services"))

    assert connections.WORK_USE_READY is True
    assert words.SERVICES["not_ready"] not in page
    assert "May look and add" in page and "Add a task to my Todoist" in page


def test_switched_off_again_it_says_so_and_uses_nothing(project, monkeypatch):
    monkeypatch.setattr(connections, "WORK_USE_READY", False)
    client = cockpit.create_app(testing=True).test_client()
    page = text_of(client.get("/services"))

    assert words.SERVICES["not_ready"] in page
    assert "May look and add" not in page and "Add a task to my Todoist" not in page
    with pytest.raises(ConfigError):
        connections.allow(project, "gmail", "look")
    with pytest.raises(ConfigError):
        notify.choose("todoist", ["needs_you"])


def test_with_nothing_allowed_no_job_gets_a_service_even_from_a_hand_set_value(project):
    hub.update_config({"services": {"gmail": "look"}})          # set by hand, at hub level

    assert "--strict-mcp-config" in argv_for(project)


# --- C1: nothing that sends, shares or invites --------------------------------------

@pytest.mark.parametrize("name", ["create_event_with_attendees", "add_attendees",
                                  "create_invitation", "add_permission", "create_permission",
                                  "create_shared_link", "add_collaborator", "create_comment",
                                  "add_user_to_channel", "create_pull_request", "sends_digest",
                                  "post_message", "create_issue"])
def test_look_and_add_refuses_what_reaches_other_people(name):
    allowed, refused = connections._judged([name], "look_and_add")

    assert allowed == [] and refused == [name]


@pytest.mark.parametrize("name", ["find_and_replace", "list_and_archive", "get_and_delete",
                                  "search_then_update_records"])
def test_look_refuses_a_reading_name_that_also_changes_things(name):
    assert connections._judged([name], "look")[0] == []


def test_the_page_no_longer_promises_more_than_the_names_can_say():
    assert "never" not in words.SERVICES["level_notes"]["look_and_add"].lower()


# --- I2: her real services found by their real entries ------------------------------

def test_an_unconfigured_repeat_does_not_hide_the_real_service(project, ready):
    connections.allow(project, "gmail", "look")

    given = argv_for(project)
    allowed = given[given.index("--allowedTools") + 1].split(",")
    assert "mcp__claude_ai_Gmail__search_threads" in allowed


def test_a_signed_out_service_is_left_out_of_the_work(project, ready):
    connections.allow(project, "google_calendar", "look")

    assert "--strict-mcp-config" in argv_for(project)


# --- I3: names with hyphens ------------------------------------------------------------

def test_tool_names_with_hyphens_are_judged_by_their_words(project, ready):
    connections.allow(project, "todoist", "look_and_add")

    given = argv_for(project)
    allowed = given[given.index("--allowedTools") + 1].split(",")
    assert "mcp__claude_ai_Todoist__add-tasks" in allowed
    assert "mcp__claude_ai_Todoist__find-tasks" in allowed
    assert "mcp__claude_ai_Todoist__delete-object" not in allowed


# --- I4 / I9: a notice counted only when it arrived, said plainly ----------------------

def at_review(project: Path) -> dict:
    made = tickets.create(project, title="A thing", words="Do it.", kind="bug")
    ticket = tickets.load(project, int(made["id"]))
    ticket["stage"] = "review"
    return tickets.write(project, ticket, "ticket 0001: at review")


def test_a_notice_through_a_signed_out_service_is_not_tried_and_says_so(project, ready,
                                                                         stub_claude):
    notify.choose("calendar", ["needs_you"])

    told = notify.tell("toolshed", at_review(project), "needs_you")

    assert told["sent"] is False and "sign in" in told["problem"]
    assert [c for c in stub_claude.calls() if "-p" in c] == []


def test_a_notice_the_job_did_not_add_is_not_counted_as_sent(project, ready, stub_claude,
                                                              monkeypatch):
    notify.choose("todoist", ["needs_you"])
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", json.dumps(
        {"type": "result", "subtype": "success", "is_error": False, "result": "",
         "structured_output": {"added": False}}))

    told = notify.tell("toolshed", at_review(project), "needs_you")

    assert told["sent"] is False and told["problem"] == notify.NOT_ADDED


def test_a_failed_notice_says_nothing_from_the_machine(project, ready, stub_claude,
                                                       monkeypatch):
    notify.choose("todoist", ["needs_you"])
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", json.dumps(
        {"type": "result", "subtype": "error", "is_error": True, "result": "boom"}))
    monkeypatch.setenv("STUB_CLAUDE_EXIT", "1")

    problem = notify.tell("toolshed", at_review(project), "needs_you")["problem"]

    assert problem == notify.NOT_ADDED
    assert "exit" not in problem and "claude" not in problem.lower()


# --- I5: a job given a service keeps no wider reach than its role --------------------

def test_a_job_with_a_service_may_not_run_commands_its_role_has_none_of(project, ready):
    connections.allow(project, "gmail", "look")

    given = argv_for(project, role="explorer")

    assert "Bash" in given[given.index("--disallowedTools") + 1].split(",")


def test_the_page_says_a_job_with_a_service_brings_her_settings():
    assert "your own settings" in words.SERVICES["learn_note"]


# --- I7 / I8: who made it, and what adding does -------------------------------------

@pytest.mark.parametrize("name", ["xyz.google/drive", "app.todoist/tasks",
                                  "io.github.todoist/tasks"])
def test_a_maker_she_knows_is_only_one_that_really_is(name):
    entry = connections._entry({"name": name, "remotes": [
        {"type": "streamable-http", "url": "https://x.example.test/mcp"}]})

    assert entry["known"] is False


def test_the_real_makers_are_still_known():
    entry = connections._entry({"name": "com.stripe/mcp", "remotes": [
        {"type": "streamable-http", "url": "https://x.example.test/mcp"}]})

    assert entry["known"] is True and entry["maker"] == "Stripe"


def test_adding_says_it_reaches_all_of_claude_and_what_will_run(project, monkeypatch):
    catalogue = {"servers": [{"server": {"name": "io.github.someone/bank", "title": "Bank",
                                         "packages": [{"registryType": "npm",
                                                       "identifier": "bank-server"}]}}]}
    monkeypatch.setattr(connections, "_fetch_catalogue", lambda query: catalogue)
    client = cockpit.create_app(testing=True).test_client()
    page = client.get("/").get_data(as_text=True)
    token = page.split(f'name="{cockpit.TOKEN_FIELD}" value="', 1)[1].split('"', 1)[0]

    answer = client.post("/services/add", data={cockpit.TOKEN_FIELD: token,
                                                "name": "io.github.someone/bank"})

    said = text_of(answer)
    assert words.SERVICES["reaches_all"] in said
    assert words.SERVICES["will_run"].format(package="bank-server") in said


def test_a_catalogue_address_that_is_not_https_is_not_offered():
    entry = connections._entry({"name": "com.stripe/mcp", "remotes": [
        {"type": "streamable-http", "url": "--help"}]})

    assert entry["addable"] is False
