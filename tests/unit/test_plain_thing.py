"""One thing she asked for: what she said, what it did, and two buttons.

Everything she needs to say yes or no, in her words: what she asked for, what it
changed with each file named for a person, what its own checks noticed as
sentences, and "Yes, carry on" or "No, change it". A stopped thing says what
stopped it and offers to try again; a thing being worked on has nothing to press.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import runs
from taller import discovery, tickets

from test_cockpit_ticket import at_review


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    return support.new_project()


@pytest.fixture
def client(project):
    return cockpit.create_app(testing=True).test_client()


@pytest.fixture
def started(monkeypatch) -> list[list[str]]:
    """The runs a click asked for, recorded instead of started."""
    import types

    seen: list[list[str]] = []

    def fake(command, log):
        seen.append(list(command))
        log.write_text("working\n", encoding="utf-8")
        return types.SimpleNamespace(pid=4321, poll=lambda: None)

    monkeypatch.setattr(runs, "_spawn", fake)
    return seen


def read(client, where: str) -> str:
    page = client.get(where).get_data(as_text=True)
    page = re.sub(r"(?s)<(style|script)\b.*?</\1>", " ", page)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def named(project: Path, names: dict[str, str]) -> None:
    ticket = tickets.load(project, 1)
    ticket["file_names"] = names
    tickets.write(project, ticket, "ticket 0001: files named")


def test_it_says_what_she_asked_for_and_what_it_did(project, client):
    at_review(project, review="The heading now uses the brand's own red.\n")

    page = read(client, "/thing/toolshed/1")

    assert "You asked for" in page and "The red is wrong." in page
    assert "What it did" in page and "The heading now uses the brand's own red." in page
    assert "Needs you" in page


def test_the_technical_list_under_the_summary_is_not_shown(project, client):
    """Taller appends what its checks found to the review, by rule id. The page
    shows those as sentences, once, and never the raw list."""
    at_review(project, review="The heading uses the danger token.\n\n"
                              "## What the gates found\n\n- constitution.commit-message-shape\n")

    page = read(client, "/thing/toolshed/1")

    assert "What the gates found" not in page
    assert "constitution.commit-message-shape" not in page


def test_files_are_named_in_words_when_the_summariser_named_them(project, client):
    at_review(project)
    named(project, {"static/css/app.css": "The page's colours"})

    page = read(client, "/thing/toolshed/1")

    assert "The page's colours" in page and "static/css/app.css" not in page


def test_a_file_the_summariser_did_not_name_falls_back_to_its_own_name(project, client):
    at_review(project)

    page = read(client, "/thing/toolshed/1")

    assert re.search(r"\bapp\b", page) and "static/css" not in page


def test_findings_are_sentences_not_rule_ids(project, client):
    at_review(project)

    page = read(client, "/thing/toolshed/1")

    assert "constitution.commit-message-shape" not in page
    assert "One of its saved notes is not written the way your project writes them" in page


def test_saying_yes_carries_it_on(project, client, started):
    at_review(project)

    client.post("/thing/toolshed/1/yes", data=token(client), follow_redirects=True)

    assert tickets.load(project, 1)["checkpoints"]["review"] == "approved"
    assert started and started[0][-4:] == ["run", "1", "--path", str(project)]


def test_saying_no_needs_words_and_records_them(project, client, started):
    at_review(project)

    refused = client.post("/thing/toolshed/1/no", data={**token(client), "reason": "  "},
                          follow_redirects=True)
    assert tickets.load(project, 1)["stage"] == "review"
    assert "reason" in html.unescape(refused.get_data(as_text=True)).lower()

    client.post("/thing/toolshed/1/no", data={**token(client), "reason": "Use the lighter red."},
                follow_redirects=True)
    ticket = tickets.load(project, 1)
    notes = (tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/notes.md") or b"").decode()
    assert ticket["stage"] == "triage" and "Use the lighter red." in notes
    assert len(started) == 1, "an empty reason started nothing; her reason starts one"


def test_a_stopped_thing_says_what_stopped_and_offers_to_try_again(project, client, started):
    at_review(project)
    tickets.block(project, 1, "the gates found what needs your decision: tests.failed (BLOCKER)")

    page = read(client, "/thing/toolshed/1")
    assert "some tests did not pass" in page.lower() and "Try again" in page
    assert "BLOCKER" not in page and "Yes, carry on" not in page
    assert "before you say yes" not in page

    client.post("/thing/toolshed/1/try-again", data=token(client), follow_redirects=True)
    assert tickets.load(project, 1)["blocked"] is None
    assert started, "trying again carries it on"


def test_while_it_works_there_is_nothing_to_press(project, client, monkeypatch):
    from cockpit import plain

    monkeypatch.setattr(plain, "live", lambda name, ticket: True)   # a run is going
    tickets.create(project, title="Heading colour", words="The red is wrong.", kind="bug")
    ticket = tickets.load(project, 1)
    ticket["stage"] = "build"
    tickets.write(project, ticket, "ticket 0001: building")

    raw = client.get("/thing/toolshed/1").get_data(as_text=True)
    page = read(client, "/thing/toolshed/1")

    assert "Working on it" in page and "Making the change" in page
    assert "Yes, carry on" not in page and "No, change it" not in page
    assert 'http-equiv="refresh"' in raw


def test_the_plan_it_followed_can_be_read(project, client):
    at_review(project, plan="1. Use the danger token in the heading.\n")

    page = read(client, "/thing/toolshed/1/plan")

    assert "Use the danger token in the heading." in page


def test_a_thing_that_is_not_hers_is_a_plain_not_found(project, client):
    answer = client.get("/thing/boathouse/1")

    assert answer.status_code == 404
    assert "Traceback" not in answer.get_data(as_text=True)


def test_the_page_names_nothing_from_the_machine(project, client):
    at_review(project)

    page = read(client, "/thing/toolshed/1").lower()

    for word in ("gate", "verdict", "checkpoint", "lane", "branch", "sha", "⑦", "severity"):
        assert word not in page, word


def test_a_plan_waiting_for_her_is_shown_itself(project, client):
    """At the plan, nothing has been done yet: what she decides on is the plan."""
    tickets.create(project, title="Heading colour", words="The red is wrong.", kind="feature")
    ticket = tickets.load(project, 1)
    ticket.update({"stage": "design", "lane": "full", "branch": "ticket/0001-heading-colour"})
    tickets.write(project, ticket, "ticket 0001: at design")
    support.git(project, "branch", ticket["branch"], "main")
    tree = tickets._worktree(project, ticket)
    tree.parent.mkdir(parents=True, exist_ok=True)
    support.git(project, "worktree", "add", "--quiet", str(tree), ticket["branch"])
    support.write(tree / tickets.ticket_dir(ticket) / "plan.md", "1. Use the brand's own red.\n")
    support.git(tree, "add", "--all")
    support.git(tree, "commit", "--quiet", "-m", "docs(plan): ticket 0001")

    page = read(client, "/thing/toolshed/1")

    assert "Its plan" in page and "Use the brand's own red." in page
    assert "What it did" not in page
    assert "Yes, carry on" in page


def at_design_with(project: Path, plan: str, summary: str | None) -> None:
    tickets.create(project, title="Heading colour", words="The red is wrong.", kind="feature")
    ticket = tickets.load(project, 1)
    ticket.update({"stage": "design", "lane": "full", "branch": "ticket/0001-heading-colour"})
    tickets.write(project, ticket, "ticket 0001: at design")
    support.git(project, "branch", ticket["branch"], "main")
    tree = tickets._worktree(project, ticket)
    tree.parent.mkdir(parents=True, exist_ok=True)
    support.git(project, "worktree", "add", "--quiet", str(tree), ticket["branch"])
    folder = tree / tickets.ticket_dir(ticket)
    support.write(folder / "plan.md", plan)
    if summary is not None:
        support.write(folder / "plan-summary.md", summary)
    support.git(tree, "add", "--all")
    support.git(tree, "commit", "--quiet", "-m", "docs(plan): ticket 0001")


def test_she_approves_the_plan_in_her_words(project, client):
    at_design_with(project, plan="1. Edit static/css/app.css: set h1 color to var(--danger).\n",
                   summary="The heading will use your brand's red.\n")

    page = read(client, "/thing/toolshed/1")

    assert "The heading will use your brand's red." in page
    assert "static/css/app.css" not in page and "var(--danger)" not in page
    assert "Show me the full plan" in page and "Yes, carry on" in page


def test_the_full_plan_is_one_click_away_and_says_who_it_is_for(project, client):
    at_design_with(project, plan="1. Edit static/css/app.css.\n",
                   summary="The heading will use your brand's red.\n")

    page = read(client, "/thing/toolshed/1/plan")

    assert "The heading will use your brand's red." in page
    assert "Edit static/css/app.css." in page
    assert "written for the builder" in page
