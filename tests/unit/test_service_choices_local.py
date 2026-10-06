"""Which services a project's work may use is kept on this computer only (her
choice, 2026-10-03): a project's own files - published with it - never say which
of her services she uses.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import support
from taller import config, connections, constitution, discovery, inference, settings

LISTING = "claude.ai Google Drive: https://drive.example.test/mcp - ✔ Connected\n"


@pytest.fixture
def projects(tmp_home: Path, identity, monkeypatch) -> tuple[Path, Path]:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    monkeypatch.setattr(connections, "WORK_USE_READY", True)
    monkeypatch.setattr(connections, "_run_list",
                        lambda: subprocess.CompletedProcess(["claude"], 0, LISTING, ""))
    monkeypatch.setattr(connections, "_learn_run", lambda service: ["search_files"])
    connections.forget()
    return support.new_project("toolshed"), support.new_project("allotment")


def argv_for(project: Path) -> list[str]:
    dispatch = inference.Dispatch(role="explorer", prompt="hello", config=config.load_hub_config(),
                                  ruleset=constitution.resolve(project),
                                  tools=inference.role_tools("explorer"))
    return inference._build(dispatch, "claude")[0]


def test_allowing_a_service_changes_nothing_in_the_project(projects):
    toolshed, _ = projects
    before = support.git(toolshed, "rev-parse", "HEAD").strip()
    settings_file = (toolshed / ".taller" / "taller.yml").read_text(encoding="utf-8")

    connections.allow(toolshed, "google_drive", "look")

    assert support.git(toolshed, "rev-parse", "HEAD").strip() == before
    assert (toolshed / ".taller" / "taller.yml").read_text(encoding="utf-8") == settings_file
    assert "google_drive" not in support.git(toolshed, "status", "--porcelain")


def test_the_choice_is_kept_on_this_computer_and_reaches_that_project_s_jobs(projects):
    toolshed, allotment = projects

    connections.allow(toolshed, "google_drive", "look")

    assert connections.allowed(toolshed) == {"google_drive": "look"}
    assert connections.allowed(allotment) == {}
    assert "google_drive" in connections.choices_file().read_text(encoding="utf-8")
    assert "mcp__claude_ai_Google_Drive__search_files" in \
        argv_for(toolshed)[argv_for(toolshed).index("--allowedTools") + 1]
    assert "--strict-mcp-config" in argv_for(allotment)


def test_a_services_value_in_a_project_s_files_is_not_used(projects):
    toolshed, _ = projects
    support.write(toolshed / ".taller" / "taller.yml",
                  (toolshed / ".taller" / "taller.yml").read_text(encoding="utf-8")
                  + "services:\n  google_drive: look\n")

    assert connections.allowed(toolshed) == {}
    assert "--strict-mcp-config" in argv_for(toolshed)


def test_the_terminal_cannot_write_a_service_into_a_project_s_files(projects):
    toolshed, _ = projects

    with pytest.raises(Exception):
        settings.set_value("services.google_drive", "look", toolshed)
