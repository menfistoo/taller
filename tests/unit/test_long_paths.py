"""Deep paths in a ticket worktree on Windows (found by the plugin acceptance test).

A rejected ticket keeps its gate verdicts on `main` under
`.taller/work/<ticket>/rejected/<stamp>/gates/`. Inside a worktree under
`~/.taller-run/ticket-worktrees/<project>-<ticket>/`, that can pass Windows'
260-character path limit, and git then refuses to check the next worktree out
("Filename too long"). Git's `core.longpaths` lifts the limit; Taller sets it
wherever it creates a worktree.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import support
from taller import discovery, gitio, tickets


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    return support.new_project()


@pytest.mark.skipif(sys.platform != "win32", reason="the 260-character limit is Windows'")
def test_a_worktree_opens_over_a_path_longer_than_windows_allows(project):
    old = tickets.create(project, title="x", words="x", kind="bug")
    ticket = tickets.create(project, title="The heading should be the danger red of the brand",
                            words="x", kind="bug")
    worktree = tickets._worktree(project, ticket)
    # As in real use: the evidence fits in the owner's checkout (where it is
    # written) and only the longer worktree path passes the limit.
    folder = f"{tickets.ticket_dir(old)}/rejected/20260928T203221/gates/"
    room = 225 - len(str(project)) - 1 - len(folder) - len(".md")   # + a temp suffix
    deep = folder + ("v" * room) + ".md"
    gitio.commit_to_main(project, {deep: b"kept\n"}, "ticket 0001: keep rejected work")
    assert len(str(project / deep)) < 260 < len(str(worktree / deep)), "must straddle the limit"

    tickets._open_worktree(project, ticket)

    # Asked of git, not Python: Python itself may not reach a path this long.
    assert gitio.git(worktree, "status", "--porcelain").stdout == ""
    assert gitio.git(worktree, "ls-files", "--", deep).stdout.strip() == deep


def test_long_paths_are_allowed_in_every_project_taller_opens_a_worktree_in(project):
    gitio.ensure_main_worktree(project)

    assert gitio.git(project, "config", "core.longpaths").stdout.strip() == "true"
