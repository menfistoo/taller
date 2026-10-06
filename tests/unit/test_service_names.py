"""How a job reaches a service she allowed (proved live, 2026-10-03).

A service she signed into on claude.ai cannot be handed to a job by its address:
the job connects, and the first call is refused ("Incompatible auth server: does
not support dynamic client registration") - only her own setup carries that
sign-in. So a job whose project allows a service loads her setup as usual, and
may use only the exact tools allowed for that service: every other service's
tools are refused by name (a refusal beats an allowance), and in unattended mode
whatever is not allowed is refused too. A job in a project that allows nothing
stays stripped of her whole setup, as before.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import support
from taller import config, connections, constitution, discovery, inference

REAL_LEARN = connections._learn_run          # kept before any test replaces it

LISTING = """claude.ai Google Drive: https://drive.example.test/mcp - \u2714 Connected
claude.ai Gmail: https://mail.example.test/mcp - \u2714 Connected
plugin:notes:notes-search: node C:/plugins/notes/server.js - \u2714 Connected
claude.ai Cloud Platform: https://cloud.example.test/mcp - ! Needs authentication
"""


@pytest.fixture
def projects(tmp_home: Path, identity, monkeypatch) -> tuple[Path, Path]:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    monkeypatch.setattr(connections, "WORK_USE_READY", True)
    monkeypatch.setattr(connections, "_run_list",
                        lambda: subprocess.CompletedProcess(["claude"], 0, LISTING, ""))
    monkeypatch.setattr(connections, "_learn_run",
                        lambda service: ["search_files", "share_file"])
    connections.forget()
    return support.new_project("toolshed"), support.new_project("allotment")


def argv_for(project: Path, role: str = "explorer") -> list[str]:
    dispatch = inference.Dispatch(role=role, prompt="hello", config=config.load_hub_config(),
                                  ruleset=constitution.resolve(project),
                                  tools=inference.role_tools(role))
    return inference._build(dispatch, "claude")[0]


def flag(argv: list[str], name: str) -> list[str]:
    return argv[argv.index(name) + 1].split(",") if name in argv else []


def test_a_service_is_reached_through_her_own_setup(projects):
    toolshed, _ = projects
    connections.allow(toolshed, "google_drive", "look")

    argv = argv_for(toolshed)

    assert "--mcp-config" not in argv
    assert "--strict-mcp-config" not in argv and "--setting-sources" not in argv
    assert "mcp__claude_ai_Google_Drive__search_files" in flag(argv, "--allowedTools")


def test_every_other_service_is_refused_by_name(projects):
    toolshed, _ = projects
    connections.allow(toolshed, "google_drive", "look")

    refused = flag(argv_for(toolshed), "--disallowedTools")

    assert "mcp__claude_ai_Gmail__*" in refused
    assert "mcp__plugin_notes_notes-search__*" in refused
    assert "mcp__claude_ai_Cloud_Platform__*" in refused
    assert "mcp__claude_ai_Google_Drive__*" not in refused
    assert "mcp__claude_ai_Google_Drive__share_file" in refused


def test_a_project_that_allows_nothing_stays_stripped(projects):
    toolshed, allotment = projects
    connections.allow(toolshed, "google_drive", "look")

    argv = argv_for(allotment)

    assert "--strict-mcp-config" in argv and "--setting-sources" in argv
    assert not [t for t in flag(argv, "--allowedTools") if t.startswith("mcp__")]


def test_the_name_a_job_knows_a_service_by_is_read_from_her_list():
    assert connections.tool_prefix("claude.ai Google Drive") == "claude_ai_Google_Drive"
    assert connections.tool_prefix("plugin:notes:notes-search") == "plugin_notes_notes-search"


def test_learning_reads_the_tools_offered_under_her_setup(projects, monkeypatch):
    init = {"type": "system", "subtype": "init", "tools": [
        "Read", "mcp__claude_ai_Google_Drive__search_files", "mcp__claude_ai_Gmail__list"]}
    seen: list[list[str]] = []

    def fake_run(argv, *args, **kwargs):
        seen.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, json.dumps(init) + "\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert REAL_LEARN("google_drive") == ["search_files"]
    assert "--strict-mcp-config" not in seen[0] and "--mcp-config" not in seen[0]


@pytest.mark.parametrize("tool", ["Agent", "Task", "PowerShell", "Bash", "Write", "Edit",
                                  "NotebookEdit", "WebFetch", "WebSearch", "Skill"])
def test_a_job_with_her_setup_keeps_to_its_own_role(projects, tool):
    """Proved live (2026-10-03): with her setup loaded, a reading job started a
    helper agent - her own settings allow it. Whatever its role lacks, it may not."""
    toolshed, _ = projects
    connections.allow(toolshed, "google_drive", "look")

    refused = flag(argv_for(toolshed, role="explorer"), "--disallowedTools")

    assert tool in refused


def test_a_role_keeps_the_tools_it_has(projects):
    toolshed, _ = projects
    connections.allow(toolshed, "google_drive", "look")

    refused = flag(argv_for(toolshed, role="architect"), "--disallowedTools")

    assert "Write" not in refused and "Edit" not in refused and "Agent" in refused


def test_her_setup_s_own_tools_are_refused_too_but_loading_and_answering_stay(projects):
    """Proved live (2026-10-03): a notice job used PushNotification from her setup -
    a tool that asks no permission - instead of its one Todoist tool."""
    toolshed, _ = projects
    connections.allow(toolshed, "google_drive", "look")
    connections.setup_tools_file().write_text(json.dumps(
        {"tools": ["Read", "ToolSearch", "StructuredOutput", "PushNotification",
                   "SendUserFile", "CronCreate"]}), encoding="utf-8")

    refused = flag(argv_for(toolshed, role="explorer"), "--disallowedTools")

    assert {"PushNotification", "SendUserFile", "CronCreate"} <= set(refused)
    assert "ToolSearch" not in refused and "StructuredOutput" not in refused
    assert "Read" not in refused


def test_without_a_record_of_her_setup_the_usual_quiet_tools_are_refused(projects):
    toolshed, _ = projects
    connections.allow(toolshed, "google_drive", "look")

    refused = flag(argv_for(toolshed, role="explorer"), "--disallowedTools")

    assert "PushNotification" in refused


def test_learning_records_what_her_setup_offers(projects, monkeypatch):
    init = {"type": "system", "subtype": "init", "tools": [
        "Read", "PushNotification", "mcp__claude_ai_Google_Drive__search_files"]}
    monkeypatch.setattr(subprocess, "run", lambda argv, *a, **k: subprocess.CompletedProcess(
        argv, 0, json.dumps(init) + "\n", ""))

    REAL_LEARN("google_drive")

    recorded = json.loads(connections.setup_tools_file().read_text(encoding="utf-8"))
    assert recorded["tools"] == ["PushNotification", "Read"]
