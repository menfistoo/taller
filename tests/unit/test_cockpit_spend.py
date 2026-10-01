"""The Spend screen: what each ticket, week and model has cost (spec 12, 7.5).

`weighted_tokens` is the figure that means something in both worlds: on a
subscription it is how hard a ticket leaned on the usage window, and on `api` it
stands in for money. Currency appears only on `api`, because a dollar figure for
a flat fee would be fiction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import support
import cockpit
from cockpit import spending
from taller import discovery, hub, tickets


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    return support.new_project()


@pytest.fixture
def client(project):
    return cockpit.create_app(testing=True).test_client()


PRICING = {"as_of": "2026-09-01",
           "claude-opus-5": {"input": 15.0, "output": 75.0,
                             "cache_write": 18.75, "cache_read": 1.5}}


def spent(project: Path, ticket_id: int, *, weighted: int, model: str = "claude-opus-5",
          partial: bool = False, created: str | None = None) -> None:
    """Put a spend block on a ticket, as `spend.fold` would have left it."""
    ticket = tickets.load(project, ticket_id)
    # The weights are what turn tokens into `weighted`; input is 1.0, so a plain
    # input count of N weighs N and the arithmetic stays readable in the test.
    ticket["spend"] = {
        "by_model": {model: {"input": weighted, "cache_write": 0, "cache_read": 0,
                             "output": 0}},
        "total_tokens": weighted, "weighted_tokens": weighted,
        "cost": None, "partial": partial, "sessions": [],
    }
    if created:
        ticket["created"] = created
    tickets.write(project, ticket, f"ticket {ticket_id:04d}: spend")


def two_tickets(project: Path, *, over: int = 1_500_000, under: int = 1_000) -> None:
    tickets.create(project, title="A small one", words="Change the heading.", kind="bug")
    tickets.create(project, title="A long one", words="Rework the loans page.",
                   kind="feature")
    spent(project, 1, weighted=under, created="2026-09-21T09:00:00")
    spent(project, 2, weighted=over, created="2026-09-28T09:00:00")


def test_each_ticket_shows_its_weighted_tokens_and_where_it_stands(project, client):
    two_tickets(project)

    found = spending.figures()
    page = client.get("/spend").get_data(as_text=True)

    assert [row["id"] for row in found["tickets"]] == [2, 1]      # the biggest first
    assert [row["budget"] for row in found["tickets"]] == ["warn", "ok"]
    assert found["warn_at"] == 1_200_000 and found["stop_at"] == 4_000_000
    assert "1,200,000" in page or "1200000" in page
    assert "A long one" in page


def test_on_a_subscription_there_is_no_currency_anywhere(project, client):
    hub.update_config({"billing": {"mode": "subscription"}, "pricing": PRICING})
    hub.commit("a price table nobody should be shown")
    two_tickets(project)

    found = spending.figures()
    page = client.get("/spend").get_data(as_text=True)

    assert found["show_cost"] is False
    assert all(row["cost"] is None for row in found["tickets"])
    assert found["totals"]["cost"] is None
    assert "$" not in page and "USD" not in page.upper()


def test_on_api_billing_the_cost_is_shown(project, client):
    hub.update_config({"billing": {"mode": "api"}, "pricing": PRICING})
    hub.commit("api billing")
    two_tickets(project)

    found = spending.figures()
    page = client.get("/spend").get_data(as_text=True)

    assert found["show_cost"] is True
    assert found["totals"]["cost"] > 0
    assert "$" in page


def test_a_lower_bound_is_marked(project, client):
    two_tickets(project)
    spent(project, 1, weighted=1_000, partial=True, created="2026-09-21T09:00:00")

    found = spending.figures()
    page = client.get("/spend").get_data(as_text=True)

    assert found["partial"] is True
    assert [row["partial"] for row in found["tickets"]] == [False, True]
    assert "at least" in page.lower()


def test_weeks_are_by_the_week_the_ticket_was_opened(project, client):
    two_tickets(project)

    found = spending.figures()

    assert [week["week"] for week in found["weeks"]] == ["2026-W40", "2026-W39"]
    assert [week["weighted"] for week in found["weeks"]] == [1_500_000, 1_000]
    assert [week["tickets"] for week in found["weeks"]] == [1, 1]


def test_every_model_is_totalled_on_its_own(project, client):
    two_tickets(project)
    spent(project, 1, weighted=1_000, model="claude-haiku-4-5-20251001",
          created="2026-09-21T09:00:00")

    found = spending.figures()
    page = client.get("/spend").get_data(as_text=True)

    assert [row["model"] for row in found["models"]] == ["claude-opus-5",
                                                         "claude-haiku-4-5-20251001"]
    assert [row["weighted"] for row in found["models"]] == [1_500_000, 1_000]
    assert "claude-haiku-4-5-20251001" in page


def test_a_project_that_cannot_be_read_does_not_empty_the_page(project, client, tmp_home):
    two_tickets(project)
    gone = support.new_project("boathouse")
    gone.rename(gone.parent / "boathouse-moved-away")

    found = spending.figures()
    page = client.get("/spend").get_data(as_text=True)

    assert [row["id"] for row in found["tickets"]] == [2, 1]
    assert found["totals"]["weighted"] == 1_501_000
    assert "boathouse" in page and "cannot be read" in page


def test_a_closed_ticket_still_counts(project, client):
    two_tickets(project)
    ticket = tickets.load(project, 1)
    ticket.update({"stage": "close", "outcome": "done"})
    tickets.write(project, ticket, "ticket 0001: closed")

    found = spending.figures()

    assert [row["id"] for row in found["tickets"]] == [2, 1]
    assert found["totals"]["weighted"] == 1_501_000
