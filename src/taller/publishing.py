"""Whether anything leaves this machine, and sending what waited (owner's rule, 2026-09-29).

Until this module, publishing was a side effect: every write to `main` pushed it
whenever the project had a remote (spec 7.3), and every new ticket opened a
GitHub issue carrying the owner's words. Both are publishing, and the owner's
rule is that nothing is published until she says so.

So both now wait for `publish.automatic`, which ships **off**. The work is
committed locally as always and recorded as `held`; `send` - `taller publish`, or
the button - opens the issues that waited, closes the ones whose work finished,
and pushes `main`, in that order, so the push carries the issue numbers too.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import config, discovery, gitio, issues

HELD = gitio.SYNC_HELD
# A ticket's own files: `.taller/work/0003-some-slug/...` -> ticket 3.
_TICKET_PATH = re.compile(r"^\.taller/work/(\d{4})-[^/]+/")
ALONE = "this project is only on this computer"
# Said to her when the project is busy for a moment - a ticket's write, a refresh.
BUSY = ("Taller is busy with this project for a moment, so nothing was done. "
        "Try again in a minute.")


def automatic(project: Path | str | None = None) -> bool:
    """`publish.automatic`, from the hub and the project's own layer. Off by default.

    Read without the profile layer: a profile describes how a kind of project is
    built, and whether the owner's work is published is not one of those things.
    """
    merged = config.load_hub_config(detect_billing=False)
    if project is not None:
        merged = config.deep_merge(merged, config.read_project_config(Path(project)))
    return bool((merged.get("publish") or {}).get("automatic", False))


def remote_of(project: Path | str) -> str:
    """The remote's address with any credential removed, or "" when there is none."""
    completed = gitio.git(project, "config", "--get", f"remote.{gitio.REMOTE}.url",
                          check=False)
    return discovery.strip_credentials(completed.stdout.strip()) if completed.returncode == 0 \
        else ""


def waiting(project: Path | str, listed: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """What has not left this machine: commits on `main`, the things they touch, and
    the issues and pull requests that waited for her.

    `listed` is the project's tickets when the caller has already read them: the
    front page asks this of every project, and reading every ticket again for it
    is the slowness part two's review found.
    """
    project = Path(project)
    remote = remote_of(project)
    if not remote:
        return {"remote": "", "commits": [], "held": False, "reason": ALONE, "things": [],
                "tickets_without_issue": [], "issues_to_close": [],
                "pull_requests_to_open": []}
    tracking = f"refs/remotes/{gitio.REMOTE}/{gitio.MAIN_BRANCH}"
    known = gitio.git(project, "rev-parse", "--verify", "--quiet", tracking,
                      check=False).returncode == 0
    span = f"{tracking}..{gitio.MAIN_BRANCH}" if known else gitio.MAIN_BRANCH
    log = gitio.git(project, "log", "--format=%x1e%H%x1f%s", "--name-only", span,
                    check=False).stdout
    commits, touched = [], set()
    for entry in log.split("\x1e"):
        head, _, names = entry.partition("\n")
        sha, _, subject = head.partition("\x1f")
        if not sha:
            continue
        commits.append({"sha": sha, "subject": subject})
        touched |= {int(match.group(1)) for match in map(_TICKET_PATH.match, names.split())
                    if match}
    if listed is None:
        listed = _tickets_of(project)
    without, to_close = _issues_waiting(project, listed)
    to_open = _pull_requests_waiting(project, listed)
    return {"remote": remote, "commits": commits,
            "held": bool(commits or without or to_close or to_open), "reason": "",
            "things": sorted(touched | set(without) | set(to_close) | set(to_open)),
            "tickets_without_issue": without, "issues_to_close": to_close,
            "pull_requests_to_open": to_open}


def _tickets_of(project: Path) -> list[dict[str, Any]]:
    from . import tickets

    return tickets.list_tickets(project)[0]


def send(project: Path | str) -> dict[str, Any]:
    """Publish everything that waited. Never raises because the remote said no.

    Issues first, then the push: recording an issue's number is itself a commit on
    `main`, and doing it first means the one push carries it.
    """
    from .errors import LockTimeout

    project = Path(project)
    remote = remote_of(project)
    if not remote:
        return {"sent": 0, "remote": "", "problem": ""}
    # First what the remote has - a pull request merged on GitHub, say - so the
    # push at the end can be accepted, and nothing is sent while offline.
    try:
        caught = gitio.catch_up(project)
    except LockTimeout:
        return {"sent": 0, "remote": remote, "problem": BUSY}
    if caught == gitio.OFFLINE:
        return {"sent": 0, "remote": remote,
                "problem": f"{remote} could not be reached, so nothing was sent. Your work is "
                           f"safe here; try again when the connection is back."}
    if caught == gitio.DIVERGED:
        return {"sent": 0, "remote": remote,
                "problem": f"{remote} has changes that cannot be combined with the ones here "
                           f"without someone deciding how, so nothing was sent. Your work is "
                           f"safe here."}
    try:
        _open_waiting_issues(project)
        _close_finished_issues(project)
        # After the issues, so each pull request's body can say `Refs #N`.
        problems = _open_waiting_pull_requests(project)
    except LockTimeout:
        return {"sent": 0, "remote": remote, "problem": BUSY}

    count = len(waiting(project)["commits"])
    if count == 0 or gitio._push(project, gitio.MAIN_BRANCH):
        return {"sent": count, "remote": remote, "problem": " ".join(problems)}
    return {"sent": 0, "remote": remote,
            "problem": " ".join(problems) or f"{remote} did not accept what was sent; your "
                                              f"work is safe here. Try again in a while."}


def _issues_waiting(project: Path, listed: list[dict[str, Any]] | None = None
                    ) -> tuple[list[int], list[int]]:
    """(tickets with no issue yet, closed tickets whose issue is still open)."""
    if issues.repo_of(project) is None:
        return [], []                       # a remote that is not GitHub has no issues
    if listed is None:
        listed = _tickets_of(project)
    without = [int(t["id"]) for t in listed
               if t.get("issue") is None and t.get("stage") != "close"]
    to_close = [int(t["id"]) for t in listed
                if t.get("issue") and t.get("stage") == "close" and not t.get("issue_closed")]
    return without, to_close


def _pull_requests_waiting(project: Path, listed: list[dict[str, Any]] | None = None
                           ) -> list[int]:
    """Tickets at ⑧ whose pull request waited for her to publish."""
    if issues.repo_of(project) is None:
        return []
    if listed is None:
        listed = _tickets_of(project)
    return [int(t["id"]) for t in listed
            if t.get("stage") == "pr" and not t.get("pr") and t.get("branch")]


def _open_waiting_pull_requests(project: Path) -> list[str]:
    """Push each waiting branch and open its pull request. Why, for any that did not."""
    from . import prs, tickets

    problems = []
    for ticket_id in _pull_requests_waiting(project):
        ticket = tickets.load(project, ticket_id)
        number, reason = prs.create(project, ticket)
        if number:
            ticket["pr"] = number
            tickets.write(project, ticket, f"ticket {ticket_id:04d}: pull request opened",
                          note=f"⑧ pull request #{number} opened when you published",
                          retry_issue=False)
        elif reason:
            # The reason - git's own words - goes to the ticket's history, not to her.
            tickets.write(project, ticket, f"ticket {ticket_id:04d}: pull request not opened",
                          note=f"⑧ pull request not opened when you published: {reason}",
                          retry_issue=False)
            problems.append(f"“{ticket['title']}” could not be sent to GitHub this time; "
                            f"it is safe here. Try again in a while.")
    return problems


def _open_waiting_issues(project: Path) -> None:
    """Each issue is opened and recorded under one hold of the project lock: an
    issue opened whose number could not then be written would be opened again at
    the next publish - her words on GitHub twice."""
    from . import locking, registry, tickets

    name = registry.get_project(project)["name"]
    for ticket_id in _issues_waiting(project)[0]:
        with locking.project_lock(name):
            ticket = tickets.load(project, ticket_id)
            if ticket.get("issue") is not None:
                continue
            number, reason = issues.open_issue(
                project, {**ticket, "words": tickets._words(project, ticket)})
            if not number:
                continue                    # tried again at the next publish
            ticket["issue"] = number
            tickets.write(project, ticket, f"ticket {ticket_id:04d}: GitHub issue #{number}",
                          note=f"GitHub issue #{number} opened when you published",
                          retry_issue=False)


def _close_finished_issues(project: Path) -> None:
    from . import tickets

    for ticket_id in _issues_waiting(project)[1]:
        ticket = tickets.load(project, ticket_id)
        if issues.close_issue(project, ticket) is None:
            ticket["issue_closed"] = True
            tickets.write(project, ticket, f"ticket {ticket_id:04d}: issue closed",
                          note=f"GitHub issue #{ticket['issue']} closed when you published",
                          retry_issue=False)
