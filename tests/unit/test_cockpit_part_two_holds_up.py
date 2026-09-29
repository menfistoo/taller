"""What the review found part two did not survive (spec 12).

Four of these are about cost: a page that lists projects must not read every
ticket of every project, and the page she approves work on must not ask GitHub
again every four seconds. The rest are two tabs doing the same thing at once,
and a folder that moved.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import interview, reading
from taller import discovery, issues, onboarding, registry, tickets

from test_cockpit_interview import ANSWERS, answer_them_all, ready      # noqa: F401
from test_cockpit_ticket import at_review


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    return support.new_project()


@pytest.fixture
def client(project):
    return cockpit.create_app(testing=True).test_client()


@pytest.fixture
def fresh(ready):
    """A client over a hub with NO `toolshed`, for the interview's own tests.

    Deliberately not `client`: that one registers a project called toolshed, and
    an interview about a project that already exists proves nothing.
    """
    return cockpit.create_app(testing=True).test_client()


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


class Counted:
    """Counts the child processes one page costs."""

    def __init__(self, monkeypatch):
        self.calls: list[list[str]] = []
        real = subprocess.run

        def counted(command, *args, **kwargs):
            self.calls.append([str(part) for part in command])
            return real(command, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", counted)

    def around(self, work) -> int:
        self.calls.clear()
        work()
        return len(self.calls)


def many_tickets(project: Path, how_many: int) -> None:
    for number in range(how_many):
        tickets.create(project, title=f"Ticket number {number}",
                       words=f"Do the {number}th thing.", kind="bug")


def test_a_page_that_lists_projects_does_not_read_their_tickets(project, client,
                                                                monkeypatch):
    """Settings and Health show project NAMES. Reading every ticket of every
    project to print a name is what made them as slow as the board."""
    many_tickets(project, 30)
    counter = Counted(monkeypatch)

    settings = counter.around(lambda: client.get("/settings"))
    health = counter.around(lambda: client.get("/health"))

    assert settings <= 12, f"{settings} child processes to list the settings"
    assert health <= 12, f"{health} child processes to list the projects"


def test_spend_reads_each_ticket_once(project, client, monkeypatch):
    """It read them twice: once through `reading.projects()` for the names, and
    again for the figures."""
    many_tickets(project, 30)
    counter = Counted(monkeypatch)

    board = counter.around(lambda: client.get("/"))
    spend = counter.around(lambda: client.get("/spend"))

    # One read of each ticket, like the board - it used to read them all twice.
    assert spend <= board + 3, f"spend cost {spend} against the board's {board}"


def test_the_rules_page_reads_the_tickets_of_no_project(project, client, monkeypatch):
    many_tickets(project, 30)
    counter = Counted(monkeypatch)

    rules = counter.around(lambda: client.get("/rules", follow_redirects=True))

    assert rules <= 20, f"{rules} child processes to show one project's rules"


def test_the_ticket_page_asks_github_once_however_often_it_refreshes(project, client,
                                                                     monkeypatch):
    """The page refreshes itself every four seconds while a run is going; a
    GitHub round-trip on each one is a page that blocks on someone else's network."""
    ticket = at_review(project)
    ticket["pr"] = 7
    tickets.write(project, ticket, "ticket 0001: a pull request")
    asked: list[list[str]] = []
    monkeypatch.setattr(issues, "repo_of", lambda path: "menfistoo/toolshed")
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: (
        asked.append(list(args)) or support.gh_json(
            {"state": "OPEN", "url": "https://github.com/menfistoo/toolshed/pull/7",
             "mergeable": "MERGEABLE", "statusCheckRollup": []})))

    for _ in range(3):
        page = client.get("/ticket/toolshed/1").get_data(as_text=True)

    assert "pull request #7" in page.lower() or "#7" in page
    assert len(asked) == 1, f"GitHub was asked {len(asked)} times for three renders"


def test_a_second_create_says_the_project_is_already_there(fresh, ready):
    answer_them_all(fresh, "toolshed", ready)
    fresh.post("/new/toolshed/create", data=token(fresh), follow_redirects=True)

    again = fresh.post("/new/toolshed/create", data=token(fresh), follow_redirects=True)

    page = again.get_data(as_text=True)
    assert "already" in page.lower() and "toolshed" in page
    assert "unanswered" not in page.lower(), "it said her answers were missing"
    assert len([e for e in registry.list_projects() if e["name"] == "toolshed"]) == 1


def test_two_tabs_creating_at_once_still_make_one_project(fresh, ready):
    answer_them_all(fresh, "toolshed", ready)
    ready_to_go = threading.Barrier(2)
    outcomes: list[str] = []

    def create() -> None:
        try:
            ready_to_go.wait(timeout=10)
            interview.create("toolshed")
            outcomes.append("made")
        except Exception as exc:                       # noqa: BLE001 - recorded, not raised
            outcomes.append(f"{type(exc).__name__}: {exc}")

    both = [threading.Thread(target=create) for _ in range(2)]
    for thread in both:
        thread.start()
    for thread in both:
        thread.join(timeout=120)

    assert [thread.is_alive() for thread in both] == [False, False], outcomes
    assert outcomes.count("made") == 1, outcomes
    assert any("already exists" in line for line in outcomes), outcomes
    assert len([e for e in registry.list_projects() if e["name"] == "toolshed"]) == 1
    assert (ready / "toolshed" / ".taller").is_dir()


def test_two_tabs_answering_at_once_do_not_lose_an_answer(fresh, ready):
    interview.start("toolshed", str(ready))
    ready_to_go = threading.Barrier(2)

    def answer(key: str, value: str) -> None:
        ready_to_go.wait(timeout=10)
        interview.answer("toolshed", key, value)

    both = [threading.Thread(target=answer, args=pair) for pair in
            (("what_it_does", "Keeps track of tools."),
             ("what_it_is_not", "It will never take payments."))]
    for thread in both:
        thread.start()
    for thread in both:
        thread.join(timeout=30)

    kept = onboarding.load_progress("toolshed")
    assert set(kept) == {"what_it_does", "what_it_is_not"}, kept


def test_checking_a_project_whose_folder_moved_says_so(project, client, tmp_home):
    gone = support.new_project("boathouse")
    gone.rename(gone.parent / "boathouse-moved-away")

    answer = client.post("/health/boathouse", data=token(client), follow_redirects=True)

    page = answer.get_data(as_text=True)
    assert answer.status_code == 200
    assert "boathouse" in page and "folder" in page.lower()
    assert "could not build this page" not in page.lower()
