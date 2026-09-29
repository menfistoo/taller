"""The pull request a ticket becomes at ⑧: its own evidence, in its body.

Spec 13: generated from `ticket.md` and the gate verdicts. It references the
issue without a closing keyword, because Taller closes the issue itself at ⑫ -
`Closes #7` would have GitHub do it the moment the branch merged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import support
from taller import discovery, gates, prs, tickets


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    return support.new_project()


def ready(project: Path, *, issue: int | None = 7) -> dict:
    """A ticket at ⑧: a branch, verdicts, a plan and a review on the branch."""
    ticket = tickets.create(project, title="Heading colour", words="The red is wrong.\nUse the "
                                                                  "brand's own red.", kind="bug")
    ticket.update({"branch": "ticket/0001-heading-colour", "stage": "pr", "issue": issue,
                   "gates": ["constitution", "size", "tests", "smoke"],
                   "verdicts": {
                       "constitution": {"result": "fail", "blocker": 0, "high": 0, "medium": 1,
                                        "low": 0, "nit": 0, "hub_sha": "a3f9c21"},
                       "size": {"result": "pass", "blocker": 0, "high": 0, "medium": 0,
                                "low": 0, "nit": 0, "hub_sha": "a3f9c21"},
                       "tests": {"result": "pass", "blocker": 0, "high": 0, "medium": 0,
                                 "low": 0, "nit": 0, "hub_sha": "a3f9c21"},
                       "smoke": {"result": "pass", "blocker": 0, "high": 0, "medium": 0,
                                 "low": 0, "nit": 0, "hub_sha": "a3f9c21"}}})
    return tickets.write(project, ticket, "ticket 0001: at pr")


def with_files_on_the_branch(project: Path, ticket: dict) -> None:
    support.git(project, "branch", ticket["branch"], "main")
    tree = tickets._worktree(project, ticket)
    tree.parent.mkdir(parents=True, exist_ok=True)
    support.git(project, "worktree", "add", "--quiet", str(tree), ticket["branch"])
    folder = tree / tickets.ticket_dir(ticket)
    folder.mkdir(parents=True, exist_ok=True)
    support.write(folder / "plan.md", "1. Use the danger token in app.css.\n")
    support.write(folder / "review.md", "The heading now uses the danger token.\n")
    verdict = gates.render_verdict(
        {"gate": "constitution", "result": "fail", "metrics": {},
         "findings": [gates.finding("constitution.commit-message-shape", "", 0,
                                    'Commit 1a2b3c4 is titled "Fixed the colour".')]},
        hub_sha="a3f9c21", prose="One commit's subject is not the conventional form.")
    (folder / "gates").mkdir(exist_ok=True)
    (folder / "gates" / "constitution.md").write_bytes(verdict)
    support.git(tree, "add", "--all")
    support.git(tree, "commit", "--quiet", "-m", "docs(plan): ticket 0001")


def test_the_title_names_the_kind_and_the_ticket(project):
    ticket = ready(project)

    assert prs.title(ticket) == "bug: Heading colour (ticket 0001)"


def test_the_body_carries_the_owners_words_the_verdicts_and_the_plan(project):
    ticket = ready(project)
    with_files_on_the_branch(project, ticket)

    body = prs.body(project, ticket)

    assert "The red is wrong." in body                      # her words, from ticket.md
    assert "Use the danger token in app.css" in body        # the plan
    assert "The heading now uses the danger token." in body  # the review summary
    assert "constitution" in body and "fail" in body and "tests" in body


def test_the_body_references_the_issue_without_closing_it(project):
    ticket = ready(project)
    with_files_on_the_branch(project, ticket)

    body = prs.body(project, ticket)

    assert "Refs #7" in body and "Closes" not in body and "Fixes" not in body


def test_medium_findings_are_in_the_body(project):
    ticket = ready(project)
    with_files_on_the_branch(project, ticket)

    body = prs.body(project, ticket)

    assert "constitution.commit-message-shape" in body and "MEDIUM" in body


def test_a_ticket_without_an_issue_says_nothing_about_one(project):
    ticket = ready(project, issue=None)
    with_files_on_the_branch(project, ticket)

    assert "Refs #" not in prs.body(project, ticket)


def test_a_project_without_a_remote_is_not_an_error(project):
    ticket = ready(project)

    assert prs.create(project, ticket) == (None, "")


def test_gh_signed_out_reports_the_reason(project, monkeypatch):
    monkeypatch.setattr("taller.issues.repo_of", lambda project: "someone/toolshed")
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)  # gh not installed
    monkeypatch.setattr(prs, "_push_branch", lambda project, branch: None)
    ticket = ready(project)
    with_files_on_the_branch(project, ticket)

    number, reason = prs.create(project, ticket)

    assert number is None and "gh is not installed" in reason


def test_a_created_pull_request_returns_its_number(project, monkeypatch):
    import subprocess

    monkeypatch.setattr("taller.issues.repo_of", lambda project: "someone/toolshed")
    seen: list[list[str]] = []

    def fake_gh(args, input=None):
        seen.append(args)
        if args[:2] == ["pr", "list"]:
            return subprocess.CompletedProcess(args, 0, "[]", "")
        return subprocess.CompletedProcess(args, 0,
                                           "https://github.com/someone/toolshed/pull/12\n", "")
    monkeypatch.setattr(discovery, "_run_gh", fake_gh)
    monkeypatch.setattr(prs, "_push_branch", lambda project, branch: None)
    ticket = ready(project)
    with_files_on_the_branch(project, ticket)

    assert prs.create(project, ticket) == (12, "")
    created = [args for args in seen if args[:2] == ["pr", "create"]]
    assert len(created) == 1
    assert "--base" in created[0] and "main" in created[0]
    assert "--head" in created[0] and ticket["branch"] in created[0]


# --- the chief at ⑧ -----------------------------------------------------------------

def test_the_chief_opens_it_once_and_then_waits(project, monkeypatch):
    import subprocess

    from taller import chief

    monkeypatch.setattr("taller.issues.repo_of", lambda project: "someone/toolshed")
    calls: list[list[str]] = []

    def fake_gh(args, input=None):
        calls.append(args)
        if args[:2] == ["pr", "list"]:
            return subprocess.CompletedProcess(args, 0, "[]", "")
        return subprocess.CompletedProcess(args, 0,
                                           "https://github.com/someone/toolshed/pull/3\n", "")
    monkeypatch.setattr(discovery, "_run_gh", fake_gh)
    monkeypatch.setattr(prs, "_push_branch", lambda project, branch: None)
    ticket = ready(project)
    with_files_on_the_branch(project, ticket)
    said: list[str] = []

    chief._pull_request(project, ticket["id"], said.append)
    assert tickets.load(project, ticket["id"])["pr"] == 3

    chief._pull_request(project, ticket["id"], said.append)

    assert len([a for a in calls if a[:2] == ["pr", "create"]]) == 1
    assert "#3" in "\n".join(said)


def test_the_chief_says_so_when_there_is_no_remote(project):
    from taller import chief

    ticket = ready(project)
    said: list[str] = []

    chief._pull_request(project, ticket["id"], said.append)

    assert "no GitHub remote" in "\n".join(said)
    assert tickets.load(project, ticket["id"])["pr"] is None
