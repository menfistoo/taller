"""The Settings screen: one surface over three files (spec 5.2, 12).

Every effective key, its value, and the layer that last set it - the same list
`taller settings` prints, from the same library call, so a value changed in
either place is the same value.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import support
import cockpit
from cockpit import configuration
from taller import discovery, hub, settings


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


def value_of(rows: list[dict], key: str):
    return next((row for row in rows if row["key"] == key), None)


def test_every_key_shows_the_layer_it_came_from(project, client):
    found = configuration.rows("toolshed")
    page = client.get("/settings?project=toolshed").get_data(as_text=True)

    row = value_of(found["rows"], "thresholds.max_file_lines")
    assert (row["value"], row["source"]) == (800, "default")
    assert "thresholds.max_file_lines" in page and "default" in page
    assert found["projects"] == ["toolshed"]


def test_pricing_and_cost_are_hidden_off_api_billing(project, client):
    hub.update_config({"billing": {"mode": "subscription"},
                       "pricing": {"as_of": "2026-09-01",
                                   "claude-opus-5": {"input": 15.0, "output": 75.0}}})
    hub.commit("a price table nobody should be shown")

    found = configuration.rows()
    page = client.get("/settings").get_data(as_text=True)

    assert not [row for row in found["rows"] if row["key"].startswith("pricing")]
    assert "pricing" not in page
    assert value_of(found["rows"], "billing.mode")["value"] == "subscription"


def test_pricing_is_shown_on_api_billing(project, client):
    hub.update_config({"billing": {"mode": "api"},
                       "pricing": {"as_of": "2026-09-01",
                                   "claude-opus-5": {"input": 15.0, "output": 75.0}}})
    hub.commit("api billing")

    found = configuration.rows()

    assert value_of(found["rows"], "pricing.claude-opus-5.input")["value"] == 15.0


def test_changing_a_value_writes_it_through_the_library(project, client):
    answer = client.post("/settings", follow_redirects=True,
                         data={**token(client), "project": "toolshed",
                               "key": "thresholds.max_file_lines", "value": "500"})

    page = answer.get_data(as_text=True)
    row = value_of(configuration.rows("toolshed")["rows"], "thresholds.max_file_lines")
    assert (row["value"], row["source"]) == (500, "project")
    assert "refreshed" in page.lower()


def test_a_hub_value_reaches_every_project(project, client):
    client.post("/settings", follow_redirects=True,
                data={**token(client), "key": "thresholds.max_fix_rounds", "value": "3"})

    row = value_of(configuration.rows()["rows"], "thresholds.max_fix_rounds")
    assert (row["value"], row["source"]) == (3, "hub")


def test_a_value_that_is_not_yaml_is_refused_with_her_words(project, client):
    answer = client.post("/settings", follow_redirects=True,
                         data={**token(client), "key": "thresholds.max_file_lines",
                               "value": "{oops"})

    page = answer.get_data(as_text=True)
    assert answer.status_code == 200 and "Traceback" not in page
    assert "is not a value" in page
    assert value_of(configuration.rows()["rows"], "thresholds.max_file_lines")["value"] == 800


def test_a_key_nothing_declares_is_refused(project, client):
    answer = client.post("/settings", follow_redirects=True,
                         data={**token(client), "key": "made.up.key", "value": "1"})

    page = answer.get_data(as_text=True)
    assert "made.up.key" in page and "no setting" in page.lower()
    assert not [row for row in configuration.rows()["rows"] if row["key"] == "made.up.key"]


def test_an_append_only_key_cannot_lose_an_entry(project, client):
    """Spec 4.4: a layer narrowing the security surface is exactly what
    append-only exists to stop, and the browser is no exception."""
    before = value_of(configuration.rows()["rows"], "paths.security_sensitive")
    assert before["value"], "the shipped floor should not be empty"

    emptied = client.post("/settings", follow_redirects=True,
                          data={**token(client), "key": "paths.security_sensitive",
                                "value": "[]"})
    replaced = client.post("/settings", follow_redirects=True,
                           data={**token(client), "key": "paths.security_sensitive",
                                 "value": "[only/this.py]"})

    assert emptied.status_code == 200 and replaced.status_code == 200
    after = value_of(configuration.rows()["rows"], "paths.security_sensitive")["value"]
    assert set(before["value"]) <= set(after), "an entry was lost from the floor"


def test_a_settings_write_needs_the_token(project, client):
    answer = client.post("/settings", data={"key": "thresholds.max_file_lines",
                                            "value": "1"})

    assert answer.status_code == 400
    assert value_of(configuration.rows()["rows"], "thresholds.max_file_lines")["value"] == 800
