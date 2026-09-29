"""The Health screen: what `taller scan` finds, when she asks for it (spec 9.5, 12).

Her decision, and the reason it is a decision: a scan reads every file in a
project and runs its tests in a throwaway checkout. No page load does that. The
page shows the last check and its age, and a button runs another.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import support
import cockpit
from cockpit import health
from taller import discovery
from taller.commands import scan


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    return support.new_project()


@pytest.fixture
def client(project):
    return cockpit.create_app(testing=True).test_client()


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def test_opening_the_page_scans_nothing(project, client, monkeypatch):
    monkeypatch.setattr(scan, "health",
                        lambda *args, **kwargs: pytest.fail("the page ran a scan"))

    answer = client.get("/health")

    assert answer.status_code == 200
    assert "toolshed" in answer.get_data(as_text=True)


def test_checking_one_project_reports_its_findings_and_its_tests(project, client):
    answer = client.post("/health/toolshed", data=token(client), follow_redirects=True)

    found = health.last("toolshed")
    page = answer.get_data(as_text=True)
    assert set(found["counts"]) == {"blocker", "high", "medium", "low", "nit"}
    assert "tests_run" in found["tests"] or found["errors"]
    assert found["gates"] == ["constitution", "size", "tests"]
    assert "toolshed" in page


def test_the_figures_are_kept_and_shown_with_their_age(project, client):
    client.post("/health/toolshed", data=token(client), follow_redirects=True)

    listed = health.projects()
    page = client.get("/health").get_data(as_text=True)

    row = [entry for entry in listed if entry["name"] == "toolshed"][0]
    assert row["checked"]["when"]
    assert row["checked"]["seconds"] >= 0
    assert "checked" in page.lower()
    assert (health.last_dir() / "toolshed.json").is_file()


def test_a_project_nobody_registered_is_refused_by_name(project, client):
    answer = client.post("/health/boathouse", data=token(client), follow_redirects=True)

    assert "boathouse" in answer.get_data(as_text=True)
    assert not (health.last_dir() / "boathouse.json").exists()


def test_a_project_whose_folder_has_moved_is_not_checked(project, client, tmp_home):
    gone = support.new_project("boathouse")
    gone.rename(gone.parent / "boathouse-moved-away")

    listed = health.projects()
    page = client.get("/health").get_data(as_text=True)

    row = [entry for entry in listed if entry["name"] == "boathouse"][0]
    assert row["available"] is False and row["problem"]
    assert "boathouse" in page


def test_checking_needs_the_token(project, client):
    answer = client.post("/health/toolshed", data={})

    assert answer.status_code == 400
    assert not (health.last_dir() / "toolshed.json").exists()
