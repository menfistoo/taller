"""Mirroring tickets to GitHub issues (spec 8.1 ① and ⑫, 13, 14).

The only part of the ticket that talks to GitHub, so it is where a failure is
absorbed: `gh` missing, signed out or offline never stops a local stage. A
project without a GitHub origin simply has no issues - not a failure, and not
worth a note.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from . import discovery, gitio


def repo_from_url(url: str | None) -> str | None:
    """`owner/name` for a github.com remote, else None."""
    key = discovery.remote_key(url) if url else None
    if not key or not key.startswith("github.com/"):
        return None
    return key.split("/", 1)[1]


def repo_of(project: Path | str) -> str | None:
    completed = gitio.git(project, "config", "--get", f"remote.{gitio.REMOTE}.url",
                          check=False)
    return repo_from_url(completed.stdout.strip() or None)


def _failure(completed: Any) -> str:
    if completed is None:
        return "gh is not installed"
    detail = (completed.stderr or completed.stdout or "").strip().splitlines()
    return detail[0] if detail else f"gh exited {completed.returncode}"


def open_issue(project: Path | str, ticket: Mapping[str, Any]) -> tuple[int | None, str]:
    """`(number, "")`, or `(None, reason)`. `(None, "")` when there is no GitHub repo."""
    repo = repo_of(project)
    if repo is None:
        return None, ""
    words = str(ticket.get("words") or "").strip()
    body = (f"{words}\n\n" if words else "") + \
        f"Tracked by Taller as ticket {int(ticket['id']):04d}."
    completed = discovery._run_gh(["issue", "create", "--repo", repo,
                                   "--title", str(ticket["title"]), "--body", body])
    if completed is None or completed.returncode != 0:
        return None, _failure(completed)
    number = re.search(r"/issues/(\d+)", completed.stdout or "")
    if not number:
        return None, "gh did not print the new issue's address"
    return int(number.group(1)), ""


def close_issue(project: Path | str, ticket: Mapping[str, Any]) -> str | None:
    """Close the ticket's issue with a one-line comment. The reason when it could not."""
    repo = repo_of(project)
    if repo is None or not ticket.get("issue"):
        return None
    comment = (f"Closed by Taller: ticket {int(ticket['id']):04d} "
               f"{'done' if ticket.get('outcome') == 'done' else 'abandoned'}.")
    completed = discovery._run_gh(["issue", "close", str(ticket["issue"]), "--repo", repo,
                                   "--comment", comment])
    if completed is None or completed.returncode != 0:
        return _failure(completed)
    return None
