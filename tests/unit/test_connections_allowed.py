"""What each project's work may use (phase G2, Task 6).

Every service is off for Taller's work until she turns it on, per project, at one
of two levels: May look, or May look and add. Task 5's measurement settled how a
job gets a service: an `--mcp-config` naming only the services its project allows,
under `--strict-mcp-config`, so nothing else loads.

Which of a service's tools it may call is said by their exact names: the live
check showed an allowance by the start of a name ("list_*") is not honoured, so
Taller learns a service's tool names once - one small request, when she first
turns it on - and allows the reading ones by name (and, at May look and add, the
creating ones). Anything not named is refused in unattended mode, and sending,
deleting, sharing and the like are refused by name besides. A service whose
tools Taller has not learned is left out: closed, never open.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import support
from taller import config, connections, constitution, discovery, inference, settings
from taller.errors import ConfigError

LISTING = """claude.ai Google Drive: https://drive.example.test/mcp - \u2714 Connected
claude.ai Todoist: https://tasks.example.test/mcp - \u2714 Connected
plugin:notes:notes-search: node C:/plugins/notes/server.js --stdio - \u2714 Connected
"""
TOOLS = {
    "google_drive": ["copy_file", "create_file", "download_file_content", "get_file_metadata",
                     "list_recent_files", "read_file_content", "search_files", "share_file",
                     "trash_file", "update_file"],
    "todoist": ["add_tasks", "find_tasks", "complete_tasks", "delete_object", "update_tasks",
                "get_overview"],
    "notes_search": ["search_notes"],
}



@pytest.fixture(autouse=True)
def work_use_ready(monkeypatch):
    """What is under the switch (connections.WORK_USE_READY), switched on."""
    monkeypatch.setattr(connections, "WORK_USE_READY", True)

@pytest.fixture(autouse=True)
def services(monkeypatch):
    monkeypatch.setattr(connections, "_run_list",
                        lambda: subprocess.CompletedProcess(["claude"], 0, LISTING, ""))
    connections.forget()


@pytest.fixture
def learned(monkeypatch) -> list[str]:
    """Learning a service's tools, as the CLI's start-up event would list them."""
    asked: list[str] = []

    def fake(prefix: str, server: dict) -> list[str] | None:
        asked.append(prefix)
        return [f"mcp__{prefix}__{name}" for name in TOOLS[prefix]]

    monkeypatch.setattr(connections, "_learn_run", fake)
    return asked


@pytest.fixture
def two_projects(tmp_home: Path, identity, monkeypatch) -> tuple[Path, Path]:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    return support.new_project("toolshed"), support.new_project("allotment")


def argv_for(project: Path, role: str = "explorer") -> list[str]:
    ruleset = constitution.resolve(project)
    dispatch = inference.Dispatch(role=role, prompt="hello", config=config.load_hub_config(),
                                  ruleset=ruleset, tools=inference.role_tools(role))
    argv, _ = inference._build(dispatch, "claude")
    return argv


def flag(argv: list[str], name: str) -> list[str]:
    return argv[argv.index(name) + 1].split(",") if name in argv else []


def service_tools(argv: list[str], name: str) -> list[str]:
    return sorted(tool for tool in flag(argv, name) if tool.startswith("mcp__"))


def test_every_service_is_off_until_she_turns_it_on(two_projects):
    toolshed, _ = two_projects

    assert connections.allowed(toolshed) == {}


def test_nothing_allowed_is_task_1_unchanged(two_projects):
    toolshed, _ = two_projects

    argv = argv_for(toolshed)

    assert "--strict-mcp-config" in argv and "--mcp-config" not in argv
    assert service_tools(argv, "--allowedTools") == []


def test_allowing_writes_the_project_layer(two_projects, learned):
    toolshed, _ = two_projects

    connections.allow(toolshed, "google_drive", "look")

    found = {key: (value, source) for key, value, source in settings.effective(toolshed)}
    assert found["services.google_drive"] == ("look", "project")
    assert connections.allowed(toolshed) == {"google_drive": "look"}


def test_a_level_that_does_not_exist_is_refused(two_projects, learned):
    toolshed, _ = two_projects

    with pytest.raises(ConfigError):
        connections.allow(toolshed, "google_drive", "everything")
    assert connections.allowed(toolshed) == {}


def test_turning_a_service_on_learns_its_tools_once(two_projects, learned):
    toolshed, allotment = two_projects

    connections.allow(toolshed, "google_drive", "look")
    connections.allow(allotment, "google_drive", "look_and_add")

    assert learned == ["google_drive"], "one small request per service, the first time"


def test_a_service_that_cannot_be_learned_changes_nothing(two_projects, monkeypatch):
    toolshed, _ = two_projects
    monkeypatch.setattr(connections, "_learn_run", lambda prefix, server: None)

    with pytest.raises(ConfigError):
        connections.allow(toolshed, "google_drive", "look")

    assert connections.allowed(toolshed) == {}


def test_look_passes_only_the_read_tools(two_projects, learned):
    toolshed, _ = two_projects
    connections.allow(toolshed, "google_drive", "look")

    argv = argv_for(toolshed)

    config_given = json.loads(argv[argv.index("--mcp-config") + 1])
    assert config_given == {"mcpServers": {"google_drive": {
        "type": "http", "url": "https://drive.example.test/mcp"}}}
    assert service_tools(argv, "--allowedTools") == [
        "mcp__google_drive__get_file_metadata", "mcp__google_drive__list_recent_files",
        "mcp__google_drive__read_file_content", "mcp__google_drive__search_files"]
    refused = service_tools(argv, "--disallowedTools")
    assert "mcp__google_drive__create_file" in refused
    assert "mcp__google_drive__share_file" in refused and "mcp__google_drive__trash_file" in refused


def test_look_and_add_never_passes_send_or_delete(two_projects, learned):
    toolshed, _ = two_projects
    connections.allow(toolshed, "todoist", "look_and_add")

    argv = argv_for(toolshed)

    assert service_tools(argv, "--allowedTools") == [
        "mcp__todoist__add_tasks", "mcp__todoist__find_tasks", "mcp__todoist__get_overview"]
    refused = service_tools(argv, "--disallowedTools")
    assert "mcp__todoist__delete_object" in refused and "mcp__todoist__update_tasks" in refused
    assert "mcp__todoist__complete_tasks" not in flag(argv, "--allowedTools")


def test_one_project_allowing_drive_does_not_give_it_to_another(two_projects, learned):
    toolshed, allotment = two_projects
    connections.allow(toolshed, "google_drive", "look")

    assert "--mcp-config" in argv_for(toolshed)
    assert "--mcp-config" not in argv_for(allotment)


def test_a_plugin_service_runs_its_own_command(two_projects, learned):
    toolshed, _ = two_projects
    connections.allow(toolshed, "notes_search", "look")

    argv = argv_for(toolshed)

    given = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]["notes_search"]
    assert given == {"command": "node", "args": ["C:/plugins/notes/server.js", "--stdio"]}


def test_a_service_that_is_gone_is_left_out_and_the_work_carries_on(two_projects, learned,
                                                                   monkeypatch):
    toolshed, _ = two_projects
    connections.allow(toolshed, "google_drive", "look")
    monkeypatch.setattr(connections, "_run_list",
                        lambda: subprocess.CompletedProcess(["claude"], 0, "", ""))
    connections.forget()

    argv = argv_for(toolshed)

    assert "--strict-mcp-config" in argv and "--mcp-config" not in argv


def test_a_service_whose_tools_are_not_known_here_is_left_out(two_projects, learned):
    toolshed, _ = two_projects
    connections.allow(toolshed, "google_drive", "look")
    connections.tools_file("google_drive").unlink()        # another machine, say

    assert "--mcp-config" not in argv_for(toolshed)


def test_turning_it_off_again_takes_it_away(two_projects, learned):
    toolshed, _ = two_projects
    connections.allow(toolshed, "google_drive", "look")

    connections.allow(toolshed, "google_drive", "off")

    assert connections.allowed(toolshed) == {}
    assert "--mcp-config" not in argv_for(toolshed)


def test_a_job_with_a_service_keeps_her_settings_for_its_sign_in(two_projects, learned):
    """Measured live: with her user settings left out, a service she signed into on
    claude.ai reports that it needs sign-in. Still only her allowed services load."""
    toolshed, allotment = two_projects
    connections.allow(toolshed, "google_drive", "look")

    with_service, without = argv_for(toolshed), argv_for(allotment)

    assert "--strict-mcp-config" in with_service and "--setting-sources" not in with_service
    assert "--setting-sources" in without
