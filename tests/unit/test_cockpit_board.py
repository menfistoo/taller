"""The Board: every open ticket of every project, in columns by stage (spec 12).

What she opens the cockpit for: which tickets are waiting for her, which are
stuck, and which have not reached GitHub. A project whose folder has moved must
not take the page down with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import support
import cockpit
from cockpit import reading
from taller import discovery, tickets


@pytest.fixture
def two(tmp_home: Path, identity, stub_claude, monkeypatch) -> list[Path]:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    monkeypatch.chdir(tmp_home)
    return [support.new_project("toolshed"), support.new_project("seed-bank")]


@pytest.fixture
def client(two):
    return cockpit.create_app(testing=True).test_client()


def a_ticket(project: Path, title: str, **fields) -> dict:
    ticket = tickets.create(project, title=title, words=f"{title}, please.", kind="bug")
    if fields:
        ticket.update(fields)
        ticket = tickets.write(project, ticket, f"ticket {ticket['id']:04d}: set up")
    return ticket


def test_every_open_ticket_of_every_project_is_on_the_board(two, client):
    a_ticket(two[0], "Heading colour")
    a_ticket(two[1], "Seed labels")

    page = client.get("/").get_data(as_text=True)

    assert "Heading colour" in page and "Seed labels" in page
    assert "toolshed" in page and "seed-bank" in page


def test_a_closed_ticket_is_not(two, client):
    a_ticket(two[0], "Old work", stage="close", outcome="done")
    a_ticket(two[0], "Live work")

    page = client.get("/").get_data(as_text=True)

    assert "Live work" in page and "Old work" not in page


def test_a_ticket_waiting_for_her_is_marked(two, client):
    ticket = a_ticket(two[0], "Heading colour", stage="review")
    loaded = tickets.load(two[0], ticket["id"])
    loaded["checkpoints"]["review"] = "pending"
    tickets.write(two[0], loaded, "ticket 0001: waiting")

    found = reading.board()

    mine = [t for column in found["stages"] for t in column["tickets"]][0]
    assert mine["waiting_for_you"] is True
    assert "review" in mine["waiting_on"]


def test_a_blocked_ticket_shows_its_reason(two, client):
    ticket = a_ticket(two[0], "Heading colour", stage="gates")
    tickets.block(two[0], ticket["id"], "the gates found what needs your decision")

    page = client.get("/").get_data(as_text=True)

    assert "needs your decision" in page
    assert "blocked" in page.lower()


def test_an_unsynced_ticket_is_marked(two, client, monkeypatch):
    a_ticket(two[0], "Heading colour")
    monkeypatch.setattr(tickets, "effective_sync", lambda project, ticket: "pending")

    found = reading.board()

    mine = [t for column in found["stages"] for t in column["tickets"]][0]
    assert mine["unsynced"] is True


def test_a_project_whose_folder_is_gone_does_not_break_the_board(two, client):
    a_ticket(two[1], "Seed labels")
    # Moved rather than deleted: the same thing as far as the registry is
    # concerned, and Windows will not delete git's read-only objects.
    two[0].rename(two[0].parent / "toolshed-moved-away")

    page = client.get("/").get_data(as_text=True)
    found = reading.projects()

    assert "Seed labels" in page                       # the other project still shows
    gone = [p for p in found if p["name"] == "toolshed"][0]
    assert gone["available"] is False and gone["problem"]
    assert "toolshed" in page


def test_the_board_names_the_stage_each_column_is(two, client):
    found = reading.board()

    labels = [column["label"] for column in found["stages"]]
    assert labels[0].endswith("intake") and "①" in labels[0]
    assert len(found["stages"]) == len(tickets.STAGES) - 1      # `close` is not a column


def test_a_ticket_links_to_its_own_page(two, client):
    a_ticket(two[0], "Heading colour")

    page = client.get("/").get_data(as_text=True)

    assert "/ticket/toolshed/1" in page


def test_what_needs_her_is_visible_without_scrolling(two, client):
    """Eleven columns do not fit a window; what needs her must not be off-screen."""
    ticket = a_ticket(two[0], "Heading colour", stage="gates")
    tickets.block(two[0], ticket["id"], "the gates found what needs your decision")

    page = client.get("/").get_data(as_text=True)
    banner = page.split("</h1>" if "</h1>" in page else "<div class=\"d-flex", 1)[0]

    assert "Heading colour" in banner


def test_a_stage_with_no_tickets_is_not_a_column(two, client):
    a_ticket(two[0], "Heading colour", stage="gates")

    page = client.get("/").get_data(as_text=True)

    assert "⑤ gates" in page
    assert "⑩ merge" not in page          # nothing is there, so it takes no room


def test_a_long_blocked_reason_is_trimmed_on_the_board(two, client):
    ticket = a_ticket(two[0], "Heading colour", stage="smoke")
    tickets.block(two[0], ticket["id"], "the app did not answer in 30 s.\n"
                  + "\n".join(f"log line {n}" for n in range(40)))

    found = reading.board()

    card = found["blocked"][0]
    assert card["blocked"] == "the app did not answer in 30 s."
    assert "log line 39" in card["blocked_in_full"]
