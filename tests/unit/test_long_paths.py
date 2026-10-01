"""Deep paths in a ticket worktree on Windows (found by the plugin acceptance test).

A rejected ticket keeps its gate verdicts on `main` under
`.taller/work/<ticket>/rejected/<stamp>/gates/`. Inside a worktree under
`~/.taller-run/ticket-worktrees/<project>-<ticket>/`, that can pass Windows'
260-character path limit, and git then refuses to check the next worktree out
("Filename too long"). Git's `core.longpaths` lifts the limit; Taller sets it
wherever it creates a worktree.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import support
from taller import discovery, gitio, tickets


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    return support.new_project()


def commit_without_a_checkout(project: Path, path: str, data: bytes, message: str) -> None:
    """A commit on `main` that no working tree writes, through a scratch index.

    The worktree is only a little deeper than the owner's checkout, by less than
    the temporary-file suffix a write there adds, so a path long enough to pass
    the limit in the worktree cannot be written in the checkout first.
    """
    env = {**os.environ, "GIT_INDEX_FILE": str(project / ".git" / "scratch-index")}

    def run(*args: str, stdin: bytes | None = None) -> str:
        return subprocess.run(["git", "-C", str(project), *args], input=stdin, env=env,
                              capture_output=True, check=True).stdout.decode().strip()

    blob = run("hash-object", "-w", "--stdin", stdin=data)
    run("read-tree", gitio.MAIN_BRANCH)
    run("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}")
    commit = run("commit-tree", run("write-tree"), "-p", gitio.MAIN_BRANCH, "-m", message)
    run("update-ref", f"refs/heads/{gitio.MAIN_BRANCH}", commit)
    os.remove(env["GIT_INDEX_FILE"])


@pytest.mark.skipif(sys.platform != "win32", reason="the 260-character limit is Windows'")
def test_a_worktree_opens_over_a_path_longer_than_windows_allows(project):
    old = tickets.create(project, title="x", words="x", kind="bug")
    ticket = tickets.create(project, title="The heading should be the danger red of the brand",
                            words="x", kind="bug")
    worktree = tickets._worktree(project, ticket)
    folder = f"{tickets.ticket_dir(old)}/rejected/20260928T203221/gates/"
    room = 265 - len(str(worktree)) - 1 - len(folder) - len(".md")
    deep = folder + ("v" * room) + ".md"
    commit_without_a_checkout(project, deep, b"kept\n", "ticket 0001: keep rejected work")
    assert len(str(worktree / deep)) > 260, "must pass the limit"

    tickets._open_worktree(project, ticket)

    # Asked of git, not Python: Python itself may not reach a path this long.
    assert gitio.git(worktree, "status", "--porcelain").stdout == ""
    assert gitio.git(worktree, "ls-files", "--", deep).stdout.strip() == deep


def test_long_paths_are_allowed_in_every_project_taller_opens_a_worktree_in(project):
    gitio.ensure_main_worktree(project)

    assert gitio.git(project, "config", "core.longpaths").stdout.strip() == "true"
