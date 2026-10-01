"""issues.py — each ticket mirrored to a GitHub issue, surviving `gh` failures.

Spec 8.1 (① opens, ⑫ closes) and 14 (`gh` unauthenticated: local stages
continue). The number is stored the moment it exists, so a retry can never
open a second issue.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

import support
from taller import discovery, issues, tickets


# The push and issue machinery itself: it runs for anyone who turns
# `publish.automatic` on, so these tests turn it on (it ships off).
pytestmark = pytest.mark.usefixtures("publish_automatically")


@pytest.fixture
def project(tmp_home: Path, identity) -> Path:
    return support.new_project()


class FakeGh:
    """Records calls; `create_results` are consumed in order."""

    def __init__(self, create_results):
        self.calls: list[list[str]] = []
        self.create_results = list(create_results)

    def __call__(self, args):
        self.calls.append(list(args))
        if args[:2] == ["issue", "create"]:
            code, out = self.create_results.pop(0)
            return subprocess.CompletedProcess(args, code, out, "" if code == 0 else out)
        return subprocess.CompletedProcess(args, 0, "", "")

    def of(self, verb: str) -> list[list[str]]:
        return [call for call in self.calls if call[:2] == ["issue", verb]]


@pytest.fixture
def on_github(monkeypatch):
    """A project whose origin is on GitHub, without touching the network."""
    monkeypatch.setattr(issues, "repo_of", lambda project: "me/tools")

    def install(results):
        fake = FakeGh(results)
        monkeypatch.setattr(discovery, "_run_gh", fake)
        return fake
    return install


def status(project: Path, ticket: dict) -> dict:
    return yaml.safe_load(tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/status.yml"))


def notes(project: Path, ticket: dict) -> str:
    return tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/notes.md").decode("utf-8")


@pytest.mark.parametrize("url, repo", [
    ("https://github.com/Me/Tools.git", "me/tools"),
    ("git@github.com:me/tools.git", "me/tools"),
    ("https://token@github.com/me/tools", "me/tools"),
    ("https://gitlab.com/me/tools.git", None),
    ("/srv/git/tools.git", None),
    (None, None),
])
def test_repo_from_url(url, repo):
    assert issues.repo_from_url(url) == repo


def test_repo_of_reads_the_origin(project: Path):
    assert issues.repo_of(project) is None
    subprocess.run(["git", "-C", str(project), "remote", "add", "origin",
                    "git@github.com:me/tools.git"], check=True)
    assert issues.repo_of(project) == "me/tools"


def test_an_issue_is_opened_at_intake_and_its_number_kept(project: Path, on_github):
    gh = on_github([(0, "https://github.com/me/tools/issues/87\n")])

    ticket = tickets.create(project, title="Danger colour", words="Fix the red.", kind="bug")

    assert ticket["issue"] == 87 and status(project, ticket)["issue"] == 87
    create = gh.of("create")[0]
    assert create[create.index("--repo") + 1] == "me/tools"
    assert create[create.index("--title") + 1] == "Danger colour"
    assert "Fix the red." in create[create.index("--body") + 1]


def test_gh_failure_leaves_the_ticket_and_retries_once_later(project: Path, on_github):
    gh = on_github([(1, "HTTP 401: Bad credentials"),
                    (0, "https://github.com/me/tools/issues/88\n")])

    ticket = tickets.create(project, title="Danger colour", words="w", kind="bug")
    assert ticket["issue"] is None and ticket["stage"] == "intake"
    assert "not opened" in notes(project, ticket)

    ticket = tickets.advance(project, ticket["id"])
    ticket = tickets.advance(project, ticket["id"], lane="fast")

    assert ticket["issue"] == 88
    assert len(gh.of("create")) == 2, "a stored number must stop further attempts"
    assert "#88 opened" in notes(project, ticket)


def test_no_remote_means_no_issue_and_no_noise(project: Path, monkeypatch):
    calls = []
    monkeypatch.setattr(discovery, "_run_gh", lambda args: calls.append(args))

    ticket = tickets.create(project, title="Local only", words="w", kind="idea")

    assert ticket["issue"] is None and calls == []
    assert "issue" not in notes(project, ticket).lower()


def test_close_comments_and_closes(project: Path, on_github):
    gh = on_github([(0, "https://github.com/me/tools/issues/87\n")])
    ticket = tickets.create(project, title="Danger colour", words="w", kind="bug")

    tickets.close(project, ticket["id"], abandon_reason="Not needed.")

    close = gh.of("close")[0]
    assert "87" in close and close[close.index("--repo") + 1] == "me/tools"
    assert "abandoned" in close[close.index("--comment") + 1]
