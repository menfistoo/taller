"""What the review found the cockpit did not survive (spec 12).

Every test here reproduces something a person would actually meet: a change too
big for a page to build, a verdict with hundreds of findings, a website that
resolves its own name to this machine, a verdict file that cannot be parsed, a
project whose git has gone, and a process id that belongs to something else now.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import reading, runs
from taller import gates, tickets

from test_cockpit_ticket import at_review, client, project      # noqa: F401


def a_big_change(project: Path, how_many: int) -> None:
    ticket = tickets.load(project, 1)
    tree = tickets._worktree(project, ticket)
    for n in range(how_many):
        support.write(tree / "static" / "css" / f"extra{n}.css",
                      "".join(f".x{n}-{line} {{ margin: {line}px; }}\n" for line in range(40)))
    support.git(tree, "add", "--all")
    support.git(tree, "commit", "--quiet", "-m", "chore: a great many files")


def test_the_file_list_does_not_read_every_changed_file(project, monkeypatch):
    """A 200-file change must not cost two git calls per file (Review Focus 5).

    `gates.diff.build` reads every file's whole content and its patch, because
    the constitution gate needs that; a page needs four numbers per file, and
    asking for the gate's data structure made a big ticket take half a minute -
    with a four-second refresh asking for it again.
    """
    at_review(project)
    a_big_change(project, 200)
    calls: list[list[str]] = []
    real = subprocess.run

    def counted(command, *args, **kwargs):
        calls.append([str(part) for part in command])
        return real(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", counted)
    found = reading.ticket_page("toolshed", 1)

    assert found["diff"]["total"] == 201
    assert len(found["diff"]["files"]) == reading.DIFF_FILES_MAX
    assert len(calls) < 30, f"{len(calls)} git calls for one page"


def test_a_verdict_with_hundreds_of_findings_is_cut(project, client):
    """Every other panel is capped; findings were not, and one gate sent a
    megabyte of HTML to the browser."""
    at_review(project)
    ticket = tickets.load(project, 1)
    tree = tickets._worktree(project, ticket)
    many = [gates.finding("brand.hardcoded-color", f"static/css/x{n}.css", n,
                          f"A literal colour on line {n}.") for n in range(400)]
    support.write(tree / tickets.ticket_dir(ticket) / "gates" / "constitution.md",
                  gates.render_verdict({"gate": "constitution", "result": "fail",
                                        "metrics": {}, "findings": many},
                                       hub_sha="a3f9c21", prose="Many literals.").decode())
    support.git(tree, "add", "--all")
    support.git(tree, "commit", "--quiet", "-m", "chore: a long verdict")

    found = reading.ticket_page("toolshed", 1)
    page = client.get("/ticket/toolshed/1").get_data(as_text=True)

    shown = [v for v in found["verdicts"] if v["gate"] == "constitution"][0]
    assert len(shown["findings"]) == reading.FINDINGS_SHOWN
    assert shown["more"] == 400 - reading.FINDINGS_SHOWN
    assert f"{shown['more']} more" in page
    assert len(page) < 200_000, f"{len(page)} bytes of HTML for one ticket"


def test_only_this_machine_is_served(client):
    """A website that points its own name at 127.0.0.1 is same-origin with the
    cockpit, and SameSite and the token would both let it through."""
    from_a_website = client.get("/", headers={"Host": "cockpit.attacker.example"})
    from_here = client.get("/", headers={"Host": "127.0.0.1:8765"})
    by_name = client.get("/", headers={"Host": "localhost:8765"})

    assert from_a_website.status_code == 400
    assert cockpit.TOKEN_FIELD not in from_a_website.get_data(as_text=True)
    assert from_here.status_code == 200 and by_name.status_code == 200


def test_a_verdict_file_that_cannot_be_read_is_said_so(project, client):
    """Its front matter is gone - truncated, hand-edited, half-written. The page
    must still show the ticket."""
    at_review(project)
    ticket = tickets.load(project, 1)
    tree = tickets._worktree(project, ticket)
    support.write(tree / tickets.ticket_dir(ticket) / "gates" / "constitution.md",
                  "This is not a verdict file any more.\n")
    support.git(tree, "add", "--all")
    support.git(tree, "commit", "--quiet", "-m", "chore: break the verdict file")

    answer = client.get("/ticket/toolshed/1")
    found = reading.ticket_page("toolshed", 1)

    assert answer.status_code == 200
    assert "The red is wrong." in answer.get_data(as_text=True)
    assert [v for v in found["verdicts"] if v["gate"] == "constitution"][0]["unreadable"]
    assert "could not be read" in answer.get_data(as_text=True)


def test_a_project_whose_git_is_gone_says_so_instead_of_no_tickets(project, client):
    """A folder that is there but is not a repository any more: a copy taken
    without `.git`, a sync mishap, a clone that stopped halfway. Saying "no open
    tickets" about a project with work in it is worse than saying nothing."""
    at_review(project)
    support.git(project, "worktree", "remove", "--force",
                str(tickets._worktree(project, tickets.load(project, 1))))
    (project / ".git").rename(project / ".git-moved-away")

    found = reading.projects()
    page = client.get("/").get_data(as_text=True)

    assert found[0]["available"] is False
    assert "git" in found[0]["problem"]
    assert "No open tickets" not in page


def test_a_reused_process_id_does_not_look_like_a_run(tmp_home, monkeypatch):
    """After a restart the cockpit has only the number it wrote down, and the
    machine hands that number to something else eventually."""
    rid = runs.run_id("toolshed", 1)
    runs.runs_dir().mkdir(parents=True, exist_ok=True)
    support.write(runs.log_path(rid), "⑤ gates\n")
    runs.remember(rid, 4321)
    monkeypatch.setattr(runs, "_alive", lambda pid: True)

    monkeypatch.setattr(runs, "_process_name", lambda pid: "notepad.exe")
    someone_else = runs.progress(rid)
    monkeypatch.setattr(runs, "_process_name", lambda pid: Path(sys.executable).name)
    our_own = runs.progress(rid)

    assert someone_else["running"] is False
    assert our_own["running"] is True


def test_the_pages_missing_from_the_install_say_what_to_do(monkeypatch):
    """`cockpit/` is a second top-level package; an install made before it
    existed does not carry it, and an import error is not a sentence."""
    from taller.commands import cockpit as command
    from taller.errors import TallerError

    monkeypatch.setitem(sys.modules, "cockpit", None)

    with pytest.raises(TallerError) as refused:
        command.application()

    assert "install" in str(refused.value).lower()
