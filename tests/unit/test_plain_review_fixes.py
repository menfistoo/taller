"""What the final review of the plain front found, each pinned by a test.

The owner's loop is: ask, let it work, look, decide, publish. The review found
places where that loop stalled - a project locked for a whole run, a thing saying
"working" when nothing was, a Publish that could not come back from a merge on
GitHub - and places where the machine's own words reached her page.
"""

from __future__ import annotations

import html
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import plain, runs, words
from taller import chief, discovery, issues, paths, publishing, scaffold, tickets
from taller.errors import LockTimeout

from test_cockpit_ticket import at_review
from test_plain_thing import at_design_with


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


@pytest.fixture
def someone_else():
    """Another live process, whose number a lock file can carry."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    yield child.pid
    child.kill()
    child.wait()


def hold(lock: Path, pid: int) -> None:
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(pid), encoding="ascii")


def read(client, where: str) -> str:
    page = client.get(where).get_data(as_text=True)
    page = re.sub(r"(?s)<(style|script)\b.*?</\1>", " ", page)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def text_of(answer) -> str:
    page = re.sub(r"(?s)<(style|script)\b.*?</\1>", " ", answer.get_data(as_text=True))
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def at(project: Path, stage: str, **fields) -> dict:
    ticket = tickets.create(project, title="Heading colour", words="The red is wrong.",
                            kind="bug")
    ticket = tickets.load(project, int(ticket["id"]))
    ticket.update({"stage": stage, **fields})
    return tickets.write(project, ticket, f"ticket {int(ticket['id']):04d}: at {stage}")


# --- C1: a run holds its own piece of work, not the whole project ----------------

def test_a_run_holds_its_own_piece_of_work_not_the_whole_project(project, someone_else):
    at(project, "build")
    hold(paths.ticket_lock("toolshed", 1), someone_else)

    tickets.create(project, title="Another", words="Something else.", kind="bug")

    assert [int(t["id"]) for t in tickets.list_tickets(project)[0]] == [1, 2]
    with pytest.raises(LockTimeout):
        chief.run(project, 1, say=lambda _: None)


def test_changing_an_answer_waits_for_the_project_and_says_so_plainly(project, client,
                                                                     someone_else):
    before = scaffold.load_brief(project)["what_it_does"]
    hold(paths.project_lock("toolshed"), someone_else)

    answer = client.post("/project/toolshed/about", follow_redirects=True,
                         data={**token(client), "what_it_does": "Something else entirely."})

    page = text_of(answer)
    assert words.BUSY in page
    assert "taller doctor" not in page and str(paths.run_dir()) not in page
    assert scaffold.load_brief(project)["what_it_does"] == before


# --- C2: "working" only when something is --------------------------------------

def test_a_thing_nothing_is_working_on_says_so_and_offers_to_carry_on(project, client):
    at(project, "build")

    page = read(client, "/thing/toolshed/1")

    assert plain.thing("toolshed", 1)["state"] == "stopped"
    assert words.THING["interrupted"] in page and "Try again" in page
    assert "Working on it" not in read(client, "/")


def test_a_thing_being_worked_on_still_says_working(project, client, someone_else):
    at(project, "build")
    hold(paths.ticket_lock("toolshed", 1), someone_else)

    assert plain.thing("toolshed", 1)["state"] == "working"


def test_a_thing_started_from_this_page_says_working_straight_away(project, client, started):
    client.post("/ask", follow_redirects=True,
                data={**token(client), "project": "toolshed", "words": "Make it red."})

    assert plain.thing("toolshed", 1)["state"] == "working"


def test_published_work_waiting_on_github_says_so_with_its_link(project, client, monkeypatch):
    monkeypatch.setattr(issues, "repo_of", lambda project: "neighbourhood/toolshed")
    at(project, "pr", pr=7, branch="ticket/0001-heading-colour")

    page = client.get("/thing/toolshed/1").get_data(as_text=True)

    assert plain.thing("toolshed", 1)["state"] == "needs_you"
    assert words.THING["merge_on_github"] in html.unescape(page)
    assert 'href="https://github.com/neighbourhood/toolshed/pull/7"' in page


def test_finished_work_in_a_project_only_on_this_computer_says_what_comes_next(project,
                                                                              client):
    at(project, "pr", branch="ticket/0001-heading-colour")

    assert plain.thing("toolshed", 1)["state"] == "needs_you"
    assert words.THING["only_here"] in read(client, "/thing/toolshed/1")


# --- C2 / I5: saying no starts the next attempt ----------------------------------

def test_saying_no_to_a_plan_starts_the_new_plan_with_her_words(project, client, started):
    at_design_with(project, plan="1. Use red.\n", summary="The heading goes red.\n")

    client.post("/thing/toolshed/1/no", follow_redirects=True,
                data={**token(client), "reason": "Use the lighter red."})

    ticket = tickets.load(project, 1)
    assert ticket["checkpoints"]["design"] == "rejected" and ticket["blocked"] is None
    assert started and started[0][-4:] == ["run", "1", "--path", str(project)]


def test_saying_no_at_the_review_starts_it_again(project, client, started):
    at_review(project)

    client.post("/thing/toolshed/1/no", follow_redirects=True,
                data={**token(client), "reason": "Use the lighter red."})

    assert tickets.load(project, 1)["stage"] == "triage"
    assert started and started[0][-4:] == ["run", "1", "--path", str(project)]


def test_a_spent_budget_says_how_to_let_it_use_more(project):
    at(project, "build", blocked={"reason": "the budget is spent: 4000001 weighted tokens "
                                            "against a stop at 4000000.",
                                  "at_stage": 4, "since": "2026-09-30T10:00:00"})

    said = plain.thing("toolshed", 1)["stopped"]

    assert "Choices" in said and "A lot" in said and "weighted" not in said


# --- I4: a finding with no sentence of its own ------------------------------------

@pytest.mark.parametrize("rule, check", [("security.sql-built-by-hand", "security"),
                                         ("ux.contrast", "ux"),
                                         ("smoke.error", "error")])
def test_a_finding_with_no_sentence_is_said_by_the_check_that_found_it(rule, check):
    said = plain.sentence({"rule": rule, "severity": "HIGH",
                           "message": "Raw SQL string concatenation in execute()"})

    assert said == words.CHECK_FOUND[check]
    assert "SQL" not in said and rule not in said


# --- I1 / I2: publishing ------------------------------------------------------------

@pytest.fixture
def on_github(tmp_home: Path, identity, stub_claude, monkeypatch, tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(bare)], check=True)
    calls: list[list[str]] = []

    def fake_gh(args, input=None, **kwargs):
        calls.append(list(args))
        if args[:2] == ["issue", "create"]:
            return subprocess.CompletedProcess(
                args, 0, "https://github.com/neighbourhood/toolshed/issues/5\n", "")
        return subprocess.CompletedProcess(args, 0, "[]", "")

    monkeypatch.setattr(discovery, "_run_gh", fake_gh)
    monkeypatch.setattr(issues, "repo_of", lambda project: "neighbourhood/toolshed")
    project = support.new_project(origin=str(bare))
    return project, bare, calls


def test_publishing_never_opens_an_issue_it_cannot_record(on_github, someone_else):
    project, _, calls = on_github
    tickets.create(project, title="A thing", words="Do it.", kind="bug")
    hold(paths.project_lock("toolshed"), someone_else)

    sent = publishing.send(project)

    assert [c for c in calls if c[:2] == ["issue", "create"]] == []
    assert tickets.load(project, 1)["issue"] is None
    assert sent["problem"] == words.BUSY


def test_publishing_brings_in_what_was_merged_on_github_first(on_github, tmp_path):
    project, bare, _ = on_github
    publishing.send(project)                               # main is on GitHub now
    elsewhere = tmp_path / "elsewhere"
    subprocess.run(["git", "clone", "--quiet", str(bare), str(elsewhere)], check=True)
    support.write(elsewhere / "MERGED.md", "merged on GitHub\n")
    support.git(elsewhere, "add", "--all")
    support.git(elsewhere, "commit", "--quiet", "-m", "Merge pull request #7")
    support.git(elsewhere, "push", "--quiet", "origin", "main")
    tickets.create(project, title="A thing", words="Do it.", kind="bug")   # held here

    sent = publishing.send(project)

    remote_main = support.git(elsewhere, "ls-remote", "origin", "refs/heads/main").split()[0]
    assert sent["problem"] == ""
    assert remote_main == support.git(project, "rev-parse", "main").strip()
    assert (project / "MERGED.md").is_file()


# --- I3: a guide too big to read ---------------------------------------------------

def test_a_guide_over_the_limit_is_refused_in_a_sentence(project):
    app = cockpit.create_app(testing=True)
    app.config["MAX_CONTENT_LENGTH"] = 4096
    client = app.test_client()
    import io

    answer = client.post("/project/toolshed/look/guide", content_type="multipart/form-data",
                         follow_redirects=True,
                         data={**token(client), "guide": (io.BytesIO(b"x" * 8192), "big.pdf")})

    assert answer.status_code == 200
    assert words.LOOK["too_big"] in text_of(answer)


# --- I6: the library's refusals, in her words --------------------------------------

def test_a_project_with_changes_made_by_hand_is_left_alone_in_a_sentence(project, client):
    readme = next(p for p in project.iterdir() if p.is_file() and p.suffix == ".md")
    readme.write_text(readme.read_text(encoding="utf-8") + "\nA note by hand.\n",
                      encoding="utf-8")

    answer = client.post("/project/toolshed/choices", follow_redirects=True,
                         data={**token(client), "choice": "tries", "option": "1"})

    page = text_of(answer)
    assert words.HAND_CHANGES in page
    assert str(project) not in page and "stash" not in page.lower()
