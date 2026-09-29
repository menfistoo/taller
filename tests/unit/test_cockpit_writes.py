"""Approving and rejecting from the browser, and the work carrying on (spec 12).

The cockpit writes through the same library call the CLI uses, under the same
locks, and never hosts the chief: a run is `taller ticket run` in its own
process, which this only starts and watches (spec 3.1).
"""

from __future__ import annotations

import os
import signal
import sys
import time
import types
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import runs
from taller import locking, paths, registry, tickets

from test_cockpit_ticket import at_review, client, project      # noqa: F401


def token_of(client) -> str:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return page.split(marker, 1)[1].split('"', 1)[0]


@pytest.fixture
def started(monkeypatch) -> list[list[str]]:
    """Records what would have been started, instead of starting it."""
    seen: list[list[str]] = []

    def fake(command, log):
        seen.append(list(command))
        log.write_text("Ticket 0001 is at ⑥ fix.\n", encoding="utf-8")
        return types.SimpleNamespace(pid=4321, poll=lambda: 0)

    monkeypatch.setattr(runs, "_spawn", fake)
    return seen


def test_approving_writes_the_approval_and_starts_a_run(project, client, started):
    at_review(project)

    answer = client.post("/ticket/toolshed/1/approve",
                         data={cockpit.TOKEN_FIELD: token_of(client)},
                         follow_redirects=True)

    assert answer.status_code == 200
    assert tickets.load(project, 1)["checkpoints"]["review"] == "approved"
    assert started, "no run was started"
    command = started[0]
    assert command[-4:] == ["run", "1", "--path", str(project)]
    assert "ticket" in command


def test_rejecting_needs_a_reason(project, client, started):
    at_review(project)

    answer = client.post("/ticket/toolshed/1/reject",
                         data={cockpit.TOKEN_FIELD: token_of(client), "reason": "   "},
                         follow_redirects=True)

    page = answer.get_data(as_text=True)
    assert "reason" in page.lower()
    assert tickets.load(project, 1)["checkpoints"]["review"] == "pending"
    assert not started


def test_rejecting_records_her_words(project, client, started):
    at_review(project)

    client.post("/ticket/toolshed/1/reject",
                data={cockpit.TOKEN_FIELD: token_of(client),
                      "reason": "Use the brand's own red"}, follow_redirects=True)

    ticket = tickets.load(project, 1)
    notes = (tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/notes.md")
             or b"").decode("utf-8")
    assert ticket["stage"] == "triage"
    assert "Use the brand's own red" in notes
    assert not started, "a rejection does not start a run"


def test_a_busy_project_says_so_plainly(project, client, started):
    """A run already holds the project's lock (Review Focus 2).

    The lock file is written directly, with a live process id in it: locks are
    re-entrant within a thread, so a test that simply took the lock would be
    let straight back in and would prove nothing.
    """
    at_review(project)
    name = registry.get_project(project)["name"]
    lock = paths.project_lock(name)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(os.getpid()), encoding="ascii")

    answer = client.post("/ticket/toolshed/1/approve",
                         data={cockpit.TOKEN_FIELD: token_of(client)},
                         follow_redirects=True)

    page = answer.get_data(as_text=True)
    assert "busy" in page.lower()
    assert "Traceback" not in page
    assert tickets.load(project, 1)["checkpoints"]["review"] == "pending"
    assert not started


def test_the_page_shows_a_run_still_going_and_then_its_result(project, monkeypatch):
    rid = runs.run_id("toolshed", 1)
    runs.runs_dir().mkdir(parents=True, exist_ok=True)
    support.write(runs.log_path(rid), "⑤ gates\n  Gates: constitution, size, tests\n")
    alive = {"yes": True}
    monkeypatch.setattr(runs, "_alive", lambda pid: alive["yes"])
    runs.remember(rid, 999)

    while_running = runs.progress(rid)
    alive["yes"] = False
    when_done = runs.progress(rid)

    assert while_running["running"] is True
    assert "Gates: constitution, size, tests" in "\n".join(while_running["lines"])
    assert when_done["running"] is False


def test_the_run_is_not_waited_for(project, client, monkeypatch):
    """A real child that outlives the request: the page must not wait for it."""
    at_review(project)
    monkeypatch.setattr(runs, "argv", lambda path, ticket_id: [
        sys.executable, "-c", "import time; time.sleep(30)"])
    began = time.monotonic()

    client.post("/ticket/toolshed/1/approve",
                data={cockpit.TOKEN_FIELD: token_of(client)}, follow_redirects=True)
    took = time.monotonic() - began
    still = runs.progress(runs.run_id("toolshed", 1))
    for child in runs._children.values():
        child.kill()

    assert still["running"] is True, "the child was gone before the page came back"
    assert took < 5, f"the page waited {took:.1f}s for a 30s run"


def test_only_the_owner_decides(project, client, started):
    """A link, a bookmark or another site's image tag must not approve anything."""
    at_review(project)

    from_a_get = client.get("/ticket/toolshed/1/approve")
    without_the_token = client.post("/ticket/toolshed/1/approve", data={})

    assert from_a_get.status_code == 405
    assert without_the_token.status_code == 400
    assert tickets.load(project, 1)["checkpoints"]["review"] == "pending"
    assert not started


def test_the_run_is_really_a_separate_program():
    """`taller ticket run`, not the chief inside the web server (spec 3.1)."""
    import inspect

    source = inspect.getsource(runs)
    assert '"ticket", "run"' in source
    assert "chief" not in source.split('"""', 2)[2], "the cockpit must not call the chief"
