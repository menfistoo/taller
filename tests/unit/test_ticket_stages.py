"""The stage machine: lanes, checkpoints, the branch at ④, reject, block, resume, close.

Spec 8.1-8.4, 7.6 and 14. Every move is a commit to `main` that names itself in
`notes.md`, so the notes are the ticket's history.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import support
from taller import paths, tickets
from taller.errors import ConfigError


@pytest.fixture
def project(tmp_home: Path, identity) -> Path:
    return support.new_project()


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def new(project: Path, title: str = "Danger colour") -> int:
    return tickets.create(project, title=title, words="Fix it.", kind="bug")["id"]


def worktree(project: Path, ticket: dict) -> Path:
    return paths.ticket_worktree(project.name, tickets.ticket_dir(ticket).split("/")[-1])


def to_build(project: Path, ticket_id: int, lane: str = "fast") -> dict:
    tickets.advance(project, ticket_id)                   # ① → ②
    return tickets.advance(project, ticket_id, lane=lane)  # ② → ④ (fast) or ③ (full)


def commit_on_branch(project: Path, ticket: dict) -> None:
    tree = worktree(project, ticket)
    (tree / "change.txt").write_text("work\n", encoding="utf-8")
    git(tree, "add", "change.txt")
    git(tree, "commit", "--quiet", "-m", "fix(ui): the change")


def notes(project: Path, ticket: dict) -> str:
    return tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/notes.md").decode("utf-8")


def test_a_fast_ticket_walks_its_ten_stages(project: Path):
    ticket_id = new(project)
    visited = [tickets.load(project, ticket_id)["stage"]]

    ticket = tickets.advance(project, ticket_id)
    visited.append(ticket["stage"])
    ticket = tickets.advance(project, ticket_id, lane="fast")
    visited.append(ticket["stage"])
    assert ticket["branch"] == "ticket/0001-danger-colour"
    assert worktree(project, ticket).is_dir()
    commit_on_branch(project, ticket)
    for _ in range(3):                                    # build, gates, smoke → review
        ticket = tickets.advance(project, ticket_id)
        visited.append(ticket["stage"])
    ticket = tickets.approve(project, ticket_id)          # review → pr
    visited.append(ticket["stage"])
    git(project, "merge", "--quiet", "--no-edit", ticket["branch"])
    ticket = tickets.advance(project, ticket_id)          # pr → merge
    visited.append(ticket["stage"])
    ticket = tickets.advance(project, ticket_id)          # merge → release
    visited.append(ticket["stage"])
    ticket = tickets.approve(project, ticket_id)          # release → close
    visited.append(ticket["stage"])

    assert tuple(visited) == tickets.LANE_STAGES["fast"]
    assert ticket["checkpoints"] == {"design": "skipped", "review": "approved",
                                     "staging": "skipped", "release": "approved"}
    assert ticket["outcome"] == "done"
    assert not worktree(project, ticket).exists()
    assert "ticket/0001-danger-colour" not in git(project, "branch", "--list")
    assert "② triage → ④ build (lane fast)" in notes(project, ticket)


def test_leaving_triage_needs_a_lane(project: Path):
    ticket_id = new(project)
    tickets.advance(project, ticket_id)

    with pytest.raises(ConfigError, match="--lane"):
        tickets.advance(project, ticket_id)


def test_the_full_lane_stops_at_design_until_approved(project: Path):
    ticket_id = new(project)
    ticket = to_build(project, ticket_id, lane="full")
    assert ticket["stage"] == "design" and ticket["branch"] is None

    with pytest.raises(ConfigError, match="taller ticket approve"):
        tickets.advance(project, ticket_id)
    assert tickets.approve(project, ticket_id)["stage"] == "build"


def test_the_lane_is_set_once_and_never_demoted(project: Path):
    ticket_id = new(project)
    to_build(project, ticket_id, lane="full")

    with pytest.raises(ConfigError, match="lane"):
        tickets.advance(project, ticket_id, lane="fast")


def test_approve_only_at_a_checkpoint(project: Path):
    ticket_id = new(project)

    with pytest.raises(ConfigError, match="checkpoint"):
        tickets.approve(project, ticket_id)


def test_merge_is_refused_until_the_branch_is_in_main(project: Path):
    ticket_id = new(project)
    ticket = to_build(project, ticket_id)
    commit_on_branch(project, ticket)
    for _ in range(3):
        tickets.advance(project, ticket_id)
    tickets.approve(project, ticket_id)                   # now at pr

    with pytest.raises(ConfigError, match="not merged"):
        tickets.advance(project, ticket_id)


def test_reject_at_review_keeps_the_evidence_then_cleans_up(project: Path):
    ticket_id = new(project)
    ticket = to_build(project, ticket_id)
    gates = worktree(project, ticket) / tickets.ticket_dir(ticket) / "gates"
    gates.mkdir(parents=True)
    (gates / "tests.md").write_text("result: fail\n", encoding="utf-8")
    for _ in range(3):
        tickets.advance(project, ticket_id)

    ticket = tickets.reject(project, ticket_id, "The red is still wrong on mobile.")

    assert ticket["stage"] == "triage" and ticket["branch"] is None
    assert ticket["chief_session"] is None
    assert ticket["checkpoints"]["review"] == "pending"
    rejected = git(project, "ls-tree", "-r", "--name-only", "main",
                   f"{tickets.ticket_dir(ticket)}/rejected").split()
    assert any(p.endswith("/gates/tests.md") for p in rejected)
    reason = next(p for p in rejected if p.endswith("/reason.md"))
    assert "still wrong on mobile" in tickets.read_main(project, reason).decode()
    assert not worktree(project, ticket).exists()
    assert "ticket/0001" not in git(project, "branch", "--list")


def test_reject_at_another_checkpoint_blocks_with_the_reason(project: Path):
    ticket_id = new(project)
    to_build(project, ticket_id, lane="full")             # at design

    ticket = tickets.reject(project, ticket_id, "Plan misses the export.")

    assert ticket["stage"] == "design"
    assert ticket["checkpoints"]["design"] == "rejected"
    assert "Plan misses the export." in ticket["blocked"]["reason"]


def test_a_blocked_ticket_keeps_its_stage_and_refuses_to_move(project: Path):
    ticket_id = new(project)
    to_build(project, ticket_id)
    tickets.advance(project, ticket_id)                   # at gates

    ticket = tickets.block(project, ticket_id, "brand.hardcoded-color survived 2 rounds")

    assert ticket["stage"] == "gates" and ticket["blocked"]["at_stage"] == 5
    with pytest.raises(ConfigError, match="blocked"):
        tickets.advance(project, ticket_id)
    ticket, _ = tickets.resume(project, ticket_id)
    assert ticket["blocked"] is None and ticket["stage"] == "gates"


def test_resume_after_a_killed_session_recreates_the_worktree(project: Path):
    """Criterion 11 / G5: nothing lost that was written down."""
    ticket_id = new(project)
    ticket = to_build(project, ticket_id)
    commit_on_branch(project, ticket)
    shutil.rmtree(worktree(project, ticket))
    git(project, "worktree", "prune")

    ticket, repairs = tickets.resume(project, ticket_id)

    tree = worktree(project, ticket)
    assert (tree / "change.txt").read_text(encoding="utf-8") == "work\n"
    assert git(tree, "rev-parse", "--abbrev-ref", "HEAD").strip() == ticket["branch"]
    assert any("worktree" in line for line in repairs)


def test_abandoning_closes_from_any_stage_and_keeps_an_unmerged_branch(project: Path):
    ticket_id = new(project)
    ticket = to_build(project, ticket_id)
    commit_on_branch(project, ticket)

    ticket = tickets.close(project, ticket_id, abandon_reason="Not needed after all.")

    assert (ticket["stage"], ticket["outcome"]) == ("close", "abandoned")
    assert not worktree(project, ticket).exists()
    assert "ticket/0001-danger-colour" in git(project, "branch", "--list"), (
        "unmerged work was deleted")
    assert "Not needed after all." in notes(project, ticket)


def test_close_without_abandon_needs_the_release_approved(project: Path):
    ticket_id = new(project)

    with pytest.raises(ConfigError, match="release"):
        tickets.close(project, ticket_id)
