"""The front page: her projects, and what she asked for in each, in plain words.

It replaces the board of twelve numbered columns at `/`. The board stays, at
`/board`, for the day something goes wrong - but what she sees when she opens
Taller names nothing from the machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import support
import cockpit
from cockpit import plain
from taller import discovery, tickets

MACHINE_WORDS = ("lane", "gate", "verdict", "checkpoint", "intake", "triage", "worktree",
                 "sha", "sync", "blocker", "①", "⑦", "⑫")


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    return support.new_project()


@pytest.fixture
def client(project):
    return cockpit.create_app(testing=True).test_client()


def visible_text(page: str) -> str:
    """What a person reads: the page without its tags, styles and attributes."""
    import html
    import re

    page = re.sub(r"(?s)<(style|script)\b.*?</\1>", " ", page)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def read(client, where: str) -> str:
    return visible_text(client.get(where).get_data(as_text=True))


def asked(project: Path, title: str, stage: str = "build", **extra) -> dict:
    ticket = tickets.create(project, title=title, words=f"{title}.", kind="bug")
    ticket.update({"stage": stage, **extra})
    return tickets.write(project, ticket, f"ticket {ticket['id']:04d}: at {stage}")


def test_the_front_page_is_her_projects_and_her_things(project, client, monkeypatch):
    monkeypatch.setattr(plain, "live", lambda name, ticket: True)   # a run is going
    asked(project, "The loans list doesn't match")

    page = read(client, "/")

    assert "My projects" in page and "toolshed" in page
    assert "The loans list doesn't match" in page
    assert "Working on it — making the change" in page


def test_the_front_page_names_nothing_from_the_machine(project, client):
    asked(project, "A thing at review", stage="review")
    asked(project, "A thing being built")
    asked(project, "A stopped thing", stage="gates",
          blocked={"reason": "tests.failed (BLOCKER) in gates", "at_stage": 5,
                   "since": "2026-09-29T10:00:00"})

    text = visible_text(client.get("/").get_data(as_text=True)).lower()

    assert not [word for word in MACHINE_WORDS if word in text]


def test_what_needs_her_comes_first(project, client):
    asked(project, "Waiting on nobody")
    asked(project, "A stopped thing", stage="gates",
          blocked={"reason": "the tests could not run", "at_stage": 5,
                   "since": "2026-09-29T10:00:00"})

    page = client.get("/").get_data(as_text=True)

    needs_you = page.index("Needs you")
    assert needs_you < page.index("A stopped thing") < page.index("Everything")


def test_a_project_with_nothing_in_it_says_so_and_offers_the_one_thing(project, client):
    page = client.get("/").get_data(as_text=True)

    assert "Nothing asked for yet." in page
    assert "Ask for something" in page


def test_a_project_that_cannot_be_found_says_so_in_words(project, client, tmp_home):
    gone = support.new_project("boathouse")
    gone.rename(gone.parent / "boathouse-moved-away")

    page = read(client, "/")

    assert "boathouse" in page and "can't find this project's folder" in page
    assert "project discover" not in page and "boathouse-moved-away" not in page


def test_forty_things_and_a_very_long_ask_still_render(project, client):
    for number in range(39):
        asked(project, f"Thing number {number}")
    asked(project, "A very long title " + "that keeps going " * 5)

    answer = client.get("/")

    assert answer.status_code == 200
    assert len(answer.get_data(as_text=True)) < 400_000


def test_finished_things_do_not_crowd_out_the_rest(project, client):
    for number in range(9):
        asked(project, f"Finished {number}", stage="close", outcome="done")
    asked(project, "Still going")

    page = client.get("/").get_data(as_text=True)

    assert "Still going" in page
    assert page.count("Finished ") <= 5 + 1
    assert "4 more done" in page


def test_the_detailed_board_is_still_there(project, client):
    answer = client.get("/board")

    assert answer.status_code == 200
    assert "every ticket" in answer.get_data(as_text=True).lower()


def test_the_stylesheet_is_served_from_this_machine(client):
    assert client.get("/static/plain.css").status_code == 200
    page = client.get("/").get_data(as_text=True).lower()
    assert "cdn" not in page and "bootstrap" not in page


def test_the_new_pages_ship_with_taller():
    """An installed Taller carries every template and the stylesheet, not only the
    top-level templates the part-one packaging listed."""
    import tomllib

    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    shipped = data["tool"]["setuptools"]["package-data"]["cockpit"]
    assert "templates/**/*.html" in shipped and "static/*" in shipped
