"""⑧ waits for her: a pull request is publishing too.

A pull request cannot exist without pushing the ticket's branch to GitHub, and
its body carries her words, the plan and the verdicts. So with publishing held,
the chief stops at ⑧ and says the work is ready to publish; pressing Publish is
what pushes the branch and opens the pull request - not the chief's next run,
which would publish without her pressing anything.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import support
from taller import chief, discovery, issues, prs, publishing, tickets

from test_prs import ready, with_files_on_the_branch


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch, tmp_path) -> Path:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(bare)], check=True)
    monkeypatch.setattr(issues, "repo_of", lambda project: "someone/toolshed")
    return support.new_project(origin=str(bare))


@pytest.fixture
def github(monkeypatch) -> dict[str, list]:
    """What would have gone to GitHub: `gh` calls, and branches pushed."""
    seen: dict[str, list] = {"gh": [], "pushed": []}

    def fake_gh(args, input=None, **kwargs):
        seen["gh"].append(list(args))
        if args[:2] == ["pr", "list"]:
            return subprocess.CompletedProcess(args, 0, "[]", "")
        if args[:2] == ["issue", "create"]:
            return subprocess.CompletedProcess(args, 0, "https://github.com/someone/toolshed/issues/5\n", "")
        return subprocess.CompletedProcess(args, 0, "https://github.com/someone/toolshed/pull/7\n", "")

    monkeypatch.setattr(discovery, "_run_gh", fake_gh)
    monkeypatch.setattr(prs, "_push_branch", lambda project, branch: seen["pushed"].append(branch))
    return seen


def at_pr(project: Path) -> dict:
    ticket = ready(project, issue=None)
    with_files_on_the_branch(project, ticket)
    return tickets.load(project, ticket["id"])


def test_a_pull_request_is_not_opened_behind_her_back(project, github):
    ticket = at_pr(project)
    said: list[str] = []

    chief._pull_request(project, ticket["id"], said.append)

    assert tickets.load(project, ticket["id"])["pr"] is None
    assert github["gh"] == [] and github["pushed"] == [], "something went to GitHub"
    assert "publish" in "\n".join(said).lower()


def test_the_stage_waits_rather_than_moving_on(project, github):
    ticket = at_pr(project)

    waits = chief._step(project, tickets.load(project, ticket["id"]), None, {}, lambda _: None)

    assert waits is True
    assert tickets.load(project, ticket["id"])["stage"] == "pr"


def test_pressing_publish_opens_it(project, github):
    ticket = at_pr(project)
    chief._pull_request(project, ticket["id"], lambda _: None)

    waiting = publishing.waiting(project)
    publishing.send(project)

    assert waiting["pull_requests_to_open"] == [ticket["id"]]
    assert tickets.load(project, ticket["id"])["pr"] == 7
    assert github["pushed"] == [ticket["branch"]]
    assert len([c for c in github["gh"] if c[:2] == ["pr", "create"]]) == 1


def test_publishing_twice_opens_it_once(project, github):
    at_pr(project)

    publishing.send(project)
    publishing.send(project)

    assert len([c for c in github["gh"] if c[:2] == ["pr", "create"]]) == 1


def test_with_publishing_on_the_chief_opens_it_as_before(project, github, publish_automatically):
    ticket = at_pr(project)

    chief._pull_request(project, ticket["id"], lambda _: None)

    assert tickets.load(project, ticket["id"])["pr"] == 7
