"""Her notice choice is kept on this computer only (found live, 2026-10-03).

Kept in Taller's shared settings, choosing Todoist re-resolved every project and
wrote the choice into each one's published snapshot. Like her service choices,
it now lives in a file on this computer, and choosing it changes no project.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import support
from taller import config, connections, discovery, notify


@pytest.fixture
def project(tmp_home: Path, identity, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    monkeypatch.setattr(connections, "WORK_USE_READY", True)
    return support.new_project()


def test_choosing_a_notice_changes_no_project(project):
    before = support.git(project, "rev-parse", "HEAD").strip()

    notify.choose("todoist", ["needs_you"])

    assert support.git(project, "rev-parse", "HEAD").strip() == before
    assert notify.configured() == {"channel": "todoist", "when": ["needs_you"]}


def test_the_choice_is_in_a_file_on_this_computer_not_in_the_shared_settings(project):
    notify.choose("calendar", ["stopped"])

    assert json.loads(notify.choice_file().read_text(encoding="utf-8"))["channel"] == "calendar"
    assert "notify" not in config.load_hub_config()
    snapshot = (project / ".taller" / "resolved.json").read_text(encoding="utf-8")
    assert "notify" not in json.loads(snapshot)


def test_off_until_she_chooses(project):
    assert notify.configured() == {"channel": None, "when": ["needs_you", "stopped"]}
