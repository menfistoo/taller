"""Choices: the four settings that matter to her, and nothing else.

Each option is one click, written to the project's own layer through the same
`settings.set_value` the terminal uses. A value set some other way that matches
no option is said to be her own, rather than lighting the wrong one.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import project_settings
from taller import config, discovery, settings


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    return support.new_project()


@pytest.fixture
def client(project):
    return cockpit.create_app(testing=True).test_client()


def read(client, where: str) -> str:
    page = client.get(where).get_data(as_text=True)
    page = re.sub(r"(?s)<(style|script)\b.*?</\1>", " ", page)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def effective(project: Path) -> dict:
    return {key: (value, source) for key, value, source in settings.effective(project)}


def lit(found: dict, choice: str) -> str | None:
    return next(c for c in found["choices"] if c["key"] == choice)["current"]


def test_each_choice_shows_what_is_in_force(project, client):
    found = project_settings.choices("toolshed")
    page = read(client, "/project/toolshed/choices")

    assert [c["key"] for c in found["choices"]] == ["publish", "budget", "tries", "language"]
    assert "Publish on its own" in page and "How much one piece of work may use" in page
    assert "Tries before it asks you" in page and "Language of the project's screens" in page


def test_choosing_writes_the_project_layer_only(project, client):
    client.post("/project/toolshed/choices", follow_redirects=True,
                data={**token(client), "choice": "tries", "option": "1"})

    value, source = effective(project)["thresholds.max_fix_rounds"]
    assert (value, source) == (1, "project")
    assert config.load_hub_config()["thresholds"]["max_fix_rounds"] == 2, "the hub moved"


def test_the_budget_is_one_choice_and_one_change(project, client):
    before = int(support.git(project, "rev-list", "--count", "main").strip())

    client.post("/project/toolshed/choices", follow_redirects=True,
                data={**token(client), "choice": "budget", "option": "little"})

    found = effective(project)
    assert found["budget.per_ticket_warn"][0] == 500_000
    assert found["budget.per_ticket_stop"][0] == 1_500_000
    assert int(support.git(project, "rev-list", "--count", "main").strip()) - before <= 2


def test_a_hand_set_value_shows_as_her_own_setting(project, client):
    settings.set_value("thresholds.max_fix_rounds", "7", project)

    found = project_settings.choices("toolshed")
    page = read(client, "/project/toolshed/choices")

    assert lit(found, "tries") is None
    assert "Your own setting" in page


def test_publishing_on_its_own_is_off_until_she_turns_it_on(project, client):
    assert lit(project_settings.choices("toolshed"), "publish") == "off"

    client.post("/project/toolshed/choices", follow_redirects=True,
                data={**token(client), "choice": "publish", "option": "on"})

    assert lit(project_settings.choices("toolshed"), "publish") == "on"
    assert effective(project)["publish.automatic"][0] is True


def test_an_untouched_project_is_normal(project, client):
    assert lit(project_settings.choices("toolshed"), "budget") == "normal"


def test_the_shipped_warning_line_is_above_what_a_plan_alone_costs():
    """Taller's own ticket 0001 used 544,374 weighted to reach a plan (2026-09-29)."""
    budget = config.SHIPPED_DEFAULTS["budget"]

    assert budget == {"per_ticket_warn": 1_200_000, "per_ticket_stop": 4_000_000}
    assert budget["per_ticket_warn"] > 544_374


def test_an_option_that_does_not_exist_is_refused(project, client):
    before = effective(project)["thresholds.max_fix_rounds"]

    client.post("/project/toolshed/choices", follow_redirects=True,
                data={**token(client), "choice": "tries", "option": "99"})

    assert effective(project)["thresholds.max_fix_rounds"] == before


def test_choosing_needs_the_token(project, client):
    answer = client.post("/project/toolshed/choices", data={"choice": "tries", "option": "1"})

    assert answer.status_code == 400


def test_everything_else_is_one_link_away(project, client):
    raw = client.get("/project/toolshed/choices").get_data(as_text=True)

    assert "Everything else, for when something goes wrong" in html.unescape(raw)
    assert 'href="/settings?project=toolshed"' in raw
