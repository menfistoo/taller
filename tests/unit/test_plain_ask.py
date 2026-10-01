"""Asking for something, and the work starting by itself.

Pick the project, say it however you like, press "Ask for it". No kind, no lane,
no title to invent: the chief names it and sorts it, as it does for any ticket
nobody has named, and the work starts at once in its own process.
"""

from __future__ import annotations

import html
import re
import types
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import runs
from taller import discovery, tickets


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    return support.new_project()


@pytest.fixture
def client(project):
    return cockpit.create_app(testing=True).test_client()


@pytest.fixture
def started(monkeypatch) -> list[list[str]]:
    seen: list[list[str]] = []

    def fake(command, log):
        seen.append(list(command))
        log.write_text("working\n", encoding="utf-8")
        return types.SimpleNamespace(pid=4321, poll=lambda: None)

    monkeypatch.setattr(runs, "_spawn", fake)
    return seen


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def text_of(answer) -> str:
    page = answer.get_data(as_text=True)
    page = re.sub(r"(?s)<(style|script)\b.*?</\1>", " ", page)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def test_the_form_is_a_project_one_box_and_one_button(project, client):
    page = text_of(client.get("/ask"))

    assert "What do you want?" in page and "toolshed" in page and "Ask for it" in page
    for machine in ("kind", "lane", "bug", "feature"):
        assert machine not in page.lower()


def test_asking_for_something_makes_it_and_starts_it(project, client, started):
    answer = client.post("/ask", follow_redirects=True,
                         data={**token(client), "project": "toolshed",
                               "words": "The loans list doesn't match."})

    ticket = tickets.load(project, 1)
    assert ticket["title"] and ticket["named_by"] is None, "the chief names it, not the form"
    assert started and started[0][-4:] == ["run", "1", "--path", str(project)]
    assert "Working on it" in text_of(answer)


def test_the_title_is_her_first_line_until_the_chief_names_it(project, client, started):
    client.post("/ask", follow_redirects=True,
                data={**token(client), "project": "toolshed",
                      "words": "The loans list doesn't match\nIt should come from the returns book."})

    ticket = tickets.load(project, 1)
    assert ticket["title"] == "The loans list doesn't match"
    assert "It should come from the returns book." in tickets._words(project, ticket)


def test_a_very_long_first_line_is_trimmed_for_the_title(project, client, started):
    long = "Please make " + "the heading much bigger and bolder " * 10

    client.post("/ask", follow_redirects=True,
                data={**token(client), "project": "toolshed", "words": long})

    assert len(tickets.load(project, 1)["title"]) <= tickets.TITLE_MAX


def test_an_empty_ask_is_refused(project, client, started):
    answer = client.post("/ask", data={**token(client), "project": "toolshed", "words": "  "})

    assert answer.status_code == 200 and "Say what you want" in text_of(answer)
    assert not started and tickets.list_tickets(project)[0] == []


def test_a_refused_ask_keeps_her_words(project, client, started):
    answer = client.post("/ask", data={**token(client), "project": "nowhere",
                                       "words": "The loans list doesn't match."})

    page = text_of(answer)
    assert "The loans list doesn't match." in page, "her words were lost"
    assert not started


def test_a_project_can_be_chosen_from_its_card(project, client):
    support.new_project("boathouse")

    page = client.get("/ask?project=boathouse").get_data(as_text=True)

    assert re.search(r'value="boathouse"[^>]*checked', page)


def test_asking_needs_the_token(project, client, started):
    answer = client.post("/ask", data={"project": "toolshed", "words": "Do it."})

    assert answer.status_code == 400 and not started
