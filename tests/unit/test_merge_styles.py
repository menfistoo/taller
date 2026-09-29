"""How a ticket's branch is recognised as merged, whichever button she used.

Her decision, 2026-09-29: **Rebase and merge** on GitHub. That rewrites the
branch's commits onto `main` with new identities, so the branch tip is no longer
an ancestor of `main` and the ancestor test alone says "not merged" for ever.
The pull request is then the only honest witness, and Taller has its number.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import support
from taller import discovery, github, tickets
from taller.errors import ConfigError

REPO = "someone/toolshed"


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    return support.new_project()


def rebased_onto_main(project: Path, branch: str) -> None:
    """What GitHub's "Rebase and merge" leaves behind: the same change, new commits."""
    support.git(project, "checkout", "-q", "-b", branch)
    support.write(project / "static" / "css" / "app.css", "h1 { color: inherit; }\n")
    support.git(project, "add", "--all")
    support.git(project, "commit", "-q", "-m", "fix(ui): the heading")
    support.git(project, "checkout", "-q", "main")
    # Main moves on first. Without that, cherry-picking rebuilds the identical
    # commit object, the branch stays an ancestor of main, and nothing is tested.
    support.write(project / "README.md", "# toolshed\n\nA later note.\n")
    support.git(project, "add", "--all")
    support.git(project, "commit", "-q", "-m", "docs: a later note")
    support.git(project, "cherry-pick", "--no-edit", branch)


def at_pr(project: Path, *, pr: int | None) -> dict:
    ticket = tickets.create(project, title="Heading", words="x", kind="bug")
    # The fast lane, so the stage after ⑧ is the merge check itself.
    ticket.update({"branch": "ticket/0001-heading", "stage": "pr", "pr": pr, "lane": "fast"})
    ticket["checkpoints"]["review"] = "approved"
    ticket["checkpoints"]["design"] = "skipped"
    ticket["checkpoints"]["staging"] = "skipped"
    return tickets.write(project, ticket, "ticket 0001: at pr")


def gh_pr(state: str):
    def fake(args, input=None):
        if args[:2] == ["pr", "view"]:
            return subprocess.CompletedProcess(args, 0, json.dumps({"state": state}), "")
        return subprocess.CompletedProcess(args, 1, "", "not stood in for")
    return fake


def test_a_rebase_and_merge_is_recognised(project, monkeypatch):
    ticket = at_pr(project, pr=5)
    rebased_onto_main(project, ticket["branch"])
    monkeypatch.setattr("taller.issues.repo_of", lambda path: REPO)
    monkeypatch.setattr(discovery, "_run_gh", gh_pr("MERGED"))

    moved = tickets.advance(project, ticket["id"])

    assert moved["stage"] == "merge"


def test_a_pull_request_still_open_is_not_merged(project, monkeypatch):
    ticket = at_pr(project, pr=5)
    rebased_onto_main(project, ticket["branch"])
    monkeypatch.setattr("taller.issues.repo_of", lambda path: REPO)
    monkeypatch.setattr(discovery, "_run_gh", gh_pr("OPEN"))

    with pytest.raises(ConfigError, match="not merged"):
        tickets.advance(project, ticket["id"])


def test_a_branch_merged_the_ordinary_way_needs_no_pull_request(project):
    ticket = at_pr(project, pr=None)
    support.git(project, "checkout", "-q", "-b", ticket["branch"])
    support.write(project / "static" / "css" / "app.css", "h1 { color: inherit; }\n")
    support.git(project, "add", "--all")
    support.git(project, "commit", "-q", "-m", "fix(ui): the heading")
    support.git(project, "checkout", "-q", "main")
    support.git(project, "merge", "-q", "--no-ff", ticket["branch"], "-m", "Merge")

    assert tickets.advance(project, ticket["id"])["stage"] == "merge"


def test_nothing_merged_anywhere_still_refuses(project, monkeypatch):
    ticket = at_pr(project, pr=5)
    support.git(project, "checkout", "-q", "-b", ticket["branch"])
    support.write(project / "static" / "css" / "app.css", "h1 { color: red; }\n")
    support.git(project, "add", "--all")
    support.git(project, "commit", "-q", "-m", "fix(ui): not merged anywhere")
    support.git(project, "checkout", "-q", "main")
    monkeypatch.setattr("taller.issues.repo_of", lambda path: REPO)
    monkeypatch.setattr(discovery, "_run_gh", gh_pr("OPEN"))

    with pytest.raises(ConfigError, match="not merged"):
        tickets.advance(project, ticket["id"])


def test_the_printed_rule_names_the_merge_style_that_works():
    text = github.ruleset_instructions(REPO)

    assert "Rebase and merge" in text
