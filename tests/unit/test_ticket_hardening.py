"""Findings of the Phase D whole-branch review, each pinned by a test.

C1 a stale `sync: pending`; C2/I4 a hand-edited `status.yml`; I1 a lost race
dropping the note; I2 a failed write after the worktree opened; I3 a rejection
that fails half way or finds its worktree gone; I5 a malformed `queue.yml`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import support
from taller import cli, discovery, doctor, gitio, paths, tickets
from taller.errors import ConfigError, GitError
from taller.prompter import ScriptedPrompter


@pytest.fixture
def project(tmp_home: Path, identity, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    return support.new_project()


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def worktree(project: Path, ticket: dict) -> Path:
    return paths.ticket_worktree(project.name, tickets.ticket_dir(ticket).split("/")[-1])


def at_review(project: Path) -> dict:
    ticket = tickets.create(project, title="First", words="w", kind="bug")
    tickets.advance(project, ticket["id"])
    ticket = tickets.advance(project, ticket["id"], lane="fast")
    return ticket


# --- C1 ----------------------------------------------------------------------

def test_a_pending_mark_that_a_later_push_carried_does_not_fail_doctor(tmp_home: Path,
                                                                       identity, publish_automatically):
    remote = tmp_home / "remote.git"
    project = support.new_project(origin=str(remote))
    first = tickets.create(project, title="Offline", words="w", kind="idea")
    assert first["sync"] == "pending"
    subprocess.run(["git", "init", "--quiet", "--bare", str(remote)], check=True)

    tickets.create(project, title="Online", words="w", kind="idea")

    check = doctor._tickets("toolshed", project)
    assert check.status == doctor.PASS, check.detail
    assert tickets.effective_sync(project, tickets.load(project, first["id"])) == "ok"


# --- C2 and I4 ---------------------------------------------------------------

EDITS = {
    "id-not-a-number": {"id": "abc"},
    "no-title": {"title": None},
    "checkpoints-empty": {"checkpoints": {}},
    "blocked-not-a-mapping": {"blocked": "yes"},
    "slug-renamed": {"slug": "renamed"},
    "unknown-lane": {"lane": "medium"},
    "unknown-sync": {"sync": "maybe"},
}


@pytest.mark.parametrize("edit", list(EDITS), ids=list(EDITS))
def test_a_hand_edited_status_is_reported_everywhere_never_a_traceback(project: Path, edit):
    ticket = tickets.create(project, title="First", words="w", kind="idea")
    where = f"{tickets.ticket_dir(ticket)}/status.yml"
    status = yaml.safe_load(tickets.read_main(project, where))
    for key, value in EDITS[edit].items():
        if value is None:
            status.pop(key)
        else:
            status[key] = value
    gitio.commit_to_main(project, {where: yaml.safe_dump(status).encode()}, "hand edit")

    found, problems = tickets.list_tickets(project)
    assert found == [] and len(problems) == 1 and "0001-first/status.yml" in problems[0]
    with pytest.raises(ConfigError, match="0001-first/status.yml"):
        tickets.load(project, 1)
    assert doctor._tickets("toolshed", project).status == doctor.FAIL
    for argv in (["show", "1"], ["transition", "1"], ["list"]):
        prompter = ScriptedPrompter({})
        code = cli.main(["ticket", *argv, "--path", str(project)], prompter)
        assert code in (0, 2), argv                       # a message, never a traceback
    assert tickets.read_main(project, ".taller/work/0001-renamed/status.yml") is None


# --- I1 ----------------------------------------------------------------------

def test_a_lost_race_still_lands_the_note_and_the_ticket_files(project: Path, monkeypatch):
    real = gitio.commit_to_main
    calls = []

    def racing(target, files, message):
        calls.append(sorted(files))
        if len(calls) == 1:
            return gitio.SYNC_PENDING                     # the swap failed: nothing landed
        return real(target, files, message)
    monkeypatch.setattr(gitio, "commit_to_main", racing)

    ticket = tickets.create(project, title="Raced", words="The owner's words.", kind="idea")

    folder = tickets.ticket_dir(ticket)
    assert b"The owner's words." in tickets.read_main(project, f"{folder}/ticket.md")
    assert b"created at" in tickets.read_main(project, f"{folder}/notes.md")
    assert yaml.safe_load(tickets.read_main(project, f"{folder}/status.yml"))["sync"] == "pending"


# --- I2 ----------------------------------------------------------------------

def test_a_write_that_fails_after_the_worktree_opened_can_be_retried(project: Path,
                                                                    monkeypatch):
    ticket = tickets.create(project, title="First", words="w", kind="bug")
    tickets.advance(project, ticket["id"])
    real = tickets.write

    def refuse(*args, **kwargs):
        raise GitError("a merge is in progress in the owner's checkout")
    monkeypatch.setattr(tickets, "write", refuse)
    with pytest.raises(GitError):
        tickets.advance(project, ticket["id"], lane="fast")
    monkeypatch.setattr(tickets, "write", real)

    ticket = tickets.advance(project, ticket["id"], lane="fast")

    assert ticket["stage"] == "build" and worktree(project, ticket).is_dir()


# --- I3 ----------------------------------------------------------------------

def test_reject_finds_the_evidence_on_the_branch_when_the_worktree_is_gone(project: Path):
    ticket = at_review(project)
    tree = worktree(project, ticket)
    gates = tree / tickets.ticket_dir(ticket) / "gates"
    gates.mkdir(parents=True)
    (gates / "tests.md").write_text("result: fail\n", encoding="utf-8")
    git(tree, "add", "--all")
    git(tree, "commit", "--quiet", "-m", "test(gates): verdict")
    for _ in range(3):
        tickets.advance(project, ticket["id"])
    shutil.rmtree(tree)
    git(project, "worktree", "prune")

    ticket = tickets.reject(project, ticket["id"], "Wrong red.")

    kept = git(project, "ls-tree", "-r", "--name-only", "main",
               f"{tickets.ticket_dir(ticket)}/rejected").split()
    assert any(path.endswith("/gates/tests.md") for path in kept)


def test_reject_that_cannot_remove_the_worktree_changes_nothing_and_says_why(
    project: Path, monkeypatch,
):
    ticket = at_review(project)
    for _ in range(3):
        tickets.advance(project, ticket["id"])
    real = gitio.git

    def stubborn(cwd, *args, check=True):
        if args[:2] == ("worktree", "remove"):
            return subprocess.CompletedProcess(args, 1, "", "Permission denied")
        return real(cwd, *args, check=check)
    monkeypatch.setattr(gitio, "git", stubborn)

    with pytest.raises(ConfigError, match="Permission denied"):
        tickets.reject(project, ticket["id"], "Wrong red.")

    ticket = tickets.load(project, ticket["id"])
    assert ticket["stage"] == "review" and ticket["branch"], "the ticket moved anyway"


# --- I5 ----------------------------------------------------------------------

@pytest.mark.parametrize("raw", [b"proposed: [unclosed\n", b"- just a list\n"],
                         ids=["not-yaml", "not-a-mapping"])
def test_a_malformed_queue_is_a_message_naming_the_file(project: Path, raw: bytes):
    gitio.commit_to_main(project, {".taller/queue.yml": raw}, "hand edit")
    prompter = ScriptedPrompter({})

    code = cli.main(["ticket", "new", "--from-queue", "--path", str(project)], prompter)

    assert code == 2 and ".taller/queue.yml" in prompter.said[-1]
