"""Her connected services, read and grouped (phase G2, Task 5).

`claude mcp list` health-checks every server and prints one line each:
`<name>: <url or command>[ (HTTP)] - <status>`. Taller reads it once, groups the
services by where they came from - her Claude account, a plugin, or added by
her - says each state in words, and folds the unconfigured repeats a plugin
brings of a service she already has. Never run live here: the output below is
made up, in the CLI's own format.
"""

from __future__ import annotations

import subprocess

import pytest

from taller import connections

LISTING = """Checking MCP server health\u2026

claude.ai Google Drive: https://drive.example.test/mcp - \u2714 Connected
claude.ai Gmail: https://mail.example.test/mcp - \u2714 Connected
claude.ai Todoist: https://tasks.example.test/mcp - \u2714 Connected
claude.ai Cloud Platform: https://cloud.example.test/mcp - ! Needs authentication
plugin:notes:notes-search: node C:/plugins/notes/server.js - \u2714 Connected
plugin:viewer:pdf: npx -y pdf-server --stdio - \u2718 Failed to connect \u2014 connection closed
plugin:team:chat: https://chat.example.test/mcp (HTTP) - ! Needs authentication
plugin:team:gmail:  (HTTP) - - Not configured
plugin:office:gmail:  (HTTP) - - Not configured
plugin:office:google calendar:  (HTTP) - - Not configured
weather: npx -y weather-server - \u2714 Connected
"""


@pytest.fixture
def listed_from(monkeypatch):
    def use(stdout: str = LISTING, code: int = 0):
        monkeypatch.setattr(connections, "_run_list",
                            lambda: subprocess.CompletedProcess(["claude"], code, stdout, ""))
        connections.forget()
        return connections.listed()
    return use


def by_name(found: list[dict], name: str) -> dict:
    return next(service for service in found if service["name"] == name)


def test_services_are_grouped_by_where_they_come_from(listed_from):
    found = listed_from()
    groups = connections.by_group()

    assert by_name(found, "Google Drive")["group"] == "account"
    assert by_name(found, "notes-search") == {**by_name(found, "notes-search"),
                                              "group": "plugin", "made_by": "notes"}
    assert by_name(found, "weather")["group"] == "yours"
    assert [s["name"] for s in groups["account"]] == ["Google Drive", "Gmail", "Todoist",
                                                      "Cloud Platform"]


def test_states_are_read_into_words(listed_from):
    found = listed_from()

    assert by_name(found, "Google Drive")["state"] == "ok"
    assert by_name(found, "Cloud Platform")["state"] == "sign_in"
    assert by_name(found, "pdf")["state"] == "broken"
    assert by_name(found, "google calendar")["state"] == "unset"
    assert connections.STATE_WORDS["sign_in"] == "Needs you to sign in"


def test_the_extra_gmails_fold_into_one(listed_from):
    found = listed_from()

    repeats = [s for s in found if s["name"].lower() == "gmail" and s["group"] == "plugin"]
    assert len(repeats) == 2 and all(s["duplicate_of"] == "Gmail" for s in repeats)
    assert by_name(found, "Gmail")["duplicate_of"] is None
    assert by_name(found, "google calendar")["duplicate_of"] is None   # nothing to repeat


def test_where_each_service_lives_is_kept_but_never_named_for_her(listed_from):
    drive = by_name(listed_from(), "Google Drive")

    assert drive["target"] == "https://drive.example.test/mcp"
    assert drive["prefix"] == "google_drive"


def test_a_listing_that_fails_is_a_sentence_not_an_empty_page(listed_from, monkeypatch):
    found = listed_from(stdout="", code=1)

    assert found == []
    assert connections.problem() == connections.LIST_FAILED


def test_a_listing_that_times_out_is_a_sentence_too(monkeypatch):
    def slow():
        raise subprocess.TimeoutExpired(["claude"], 60)

    monkeypatch.setattr(connections, "_run_list", slow)
    connections.forget()

    assert connections.listed() == []
    assert connections.problem() == connections.LIST_FAILED


def test_the_list_is_read_once_a_minute(listed_from, monkeypatch):
    listed_from()
    calls = []
    monkeypatch.setattr(connections, "_run_list", lambda: calls.append(1))

    connections.listed()

    assert calls == [], "a second read within a minute uses what was read"
