"""The pull request a ticket becomes at ⑧ (spec 13).

Its body is written from what the ticket already has: the owner's own words, the
approved plan, the review summary, and every gate verdict with its counts - so
the pull request carries its evidence rather than pointing at a machine only she
can see.

The issue is referenced as `Refs #N`, never `Closes #N`: Taller closes the issue
itself at ⑫ (§13), and a closing keyword would have GitHub close it the moment
the branch merged, before the release checkpoint.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from . import discovery, gates, gitio, issues, tickets

COUNTS = ("blocker", "high", "medium", "low", "nit")


def title(ticket: Mapping[str, Any]) -> str:
    return f"{ticket.get('kind', 'change')}: {ticket['title']} (ticket {int(ticket['id']):04d})"


def body(project: Path | str, ticket: Mapping[str, Any]) -> str:
    project = Path(project)
    parts = [f"Ticket {int(ticket['id']):04d}, carried by Taller.", ""]
    words = tickets._words(project, ticket).strip()
    if words:
        parts += ["## What was asked", "", words, ""]
    review = tickets.on_branch(project, ticket, "review.md")
    if review:
        parts += ["## What changed", "", review.strip(), ""]
    plan = tickets.on_branch(project, ticket, "plan.md")
    if plan:
        parts += ["## The plan it followed", "", plan.strip(), ""]
    parts += _verdicts(project, ticket)
    if ticket.get("issue"):
        parts += [f"Refs #{int(ticket['issue'])}.", ""]
    parts.append(f"Gate verdicts in full: `{tickets.ticket_dir(ticket)}/gates/` on this branch.")
    return "\n".join(parts)


def create(project: Path | str, ticket: Mapping[str, Any]) -> tuple[int | None, str]:
    """`(number, "")`, `(None, reason)`, or `(None, "")` when there is no GitHub repo.

    The branch is pushed first: GitHub cannot open a pull request for a branch it
    has never seen, and nothing else in Taller pushes anything but `main`. An open
    pull request for this branch is adopted rather than duplicated.
    """
    project = Path(project)
    branch = str(ticket["branch"])
    repo = issues.repo_of(project)
    if repo is None:
        return None, ""

    existing, reason = _existing(repo, branch)
    if existing or reason:
        return existing, reason
    pushed = _push_branch(project, branch)
    if pushed:
        return None, pushed
    completed = discovery._run_gh(["pr", "create", "--repo", repo, "--base", gitio.MAIN_BRANCH,
                                   "--head", branch, "--title", title(ticket),
                                   "--body-file", "-"], input=body(project, ticket))
    if completed is None or completed.returncode != 0:
        return None, issues._failure(completed)
    number = re.search(r"/pull/(\d+)", completed.stdout or "")
    if not number:
        return None, "gh did not print the new pull request's address"
    return int(number.group(1)), ""


def state(project: Path | str, ticket: Mapping[str, Any]) -> dict[str, Any]:
    """What GitHub says about this ticket's pull request, now (spec 12).

    `status.yml` keeps the number Taller opened; only GitHub knows whether it was
    merged, closed, or had its checks turn red since. Asking is never fatal: a
    missing `gh`, no repository or no network becomes `problem`, because a page
    that cannot reach GitHub must still show the ticket.
    """
    blank = {"number": None, "state": "", "url": "", "checks": "", "problem": ""}
    number = ticket.get("pr")
    if not number:
        return blank
    repo = issues.repo_of(project)
    if repo is None:
        return {**blank, "number": int(number),
                "problem": "this project has no GitHub repository, so its number "
                           "cannot be checked"}
    completed = discovery._run_gh(["pr", "view", str(number), "--repo", repo, "--json",
                                   "state,url,mergeable,statusCheckRollup"])
    if completed is None or completed.returncode != 0:
        return {**blank, "number": int(number), "problem": issues._failure(completed)}
    try:
        found = json.loads(completed.stdout or "{}")
    except ValueError:
        return {**blank, "number": int(number),
                "problem": "gh did not answer with a pull request"}
    return {
        "number": int(number),
        "state": str(found.get("state", "")).lower(),
        "url": str(found.get("url", "")),
        "mergeable": str(found.get("mergeable", "")).lower(),
        "checks": _checks(found.get("statusCheckRollup") or []),
        "problem": "",
    }


def _checks(rollup: list[Any]) -> str:
    """`3 passed`, `1 failed, 2 passed`, or "" when GitHub reported no checks."""
    counted: dict[str, int] = {}
    for check in rollup:
        if not isinstance(check, Mapping):
            continue
        outcome = str(check.get("conclusion") or check.get("status") or "").lower()
        counted[outcome or "pending"] = counted.get(outcome or "pending", 0) + 1
    return ", ".join(f"{number} {name}" for name, number in sorted(counted.items()))


def _push_branch(project: Path, branch: str) -> str | None:
    """Put the branch on the remote. The reason when it could not."""
    completed = gitio.git(project, "push", "--set-upstream", gitio.REMOTE, branch, check=False)
    if completed.returncode == 0:
        return None
    detail = (completed.stderr or completed.stdout or "").strip().splitlines()
    last = detail[-1] if detail else "git said nothing"
    if "workflow" in " ".join(detail).lower():
        return (f"the push was refused because the token may not touch workflow files: "
                f"`gh auth refresh -s workflow`, then run this again ({last})")
    return f"the branch could not be pushed: {last}"


def _existing(repo: str, branch: str) -> tuple[int | None, str]:
    """An open pull request for this branch, or a reason not to open a second one."""
    completed = discovery._run_gh(["pr", "list", "--repo", repo, "--head", branch,
                                   "--state", "all", "--json", "number,state"])
    if completed is None or completed.returncode != 0:
        return None, ""                   # cannot ask: carry on and let `create` report
    try:
        found = json.loads(completed.stdout or "[]")
    except ValueError:
        return None, ""
    open_ = [p for p in found if str(p.get("state", "")).upper() == "OPEN"]
    if open_:
        return int(open_[0]["number"]), ""
    if found:
        numbers = ", ".join(f"#{p['number']}" for p in found)
        return None, (f"a pull request for {branch} was already opened and closed ({numbers}); "
                      f"reopen it on GitHub, or delete the branch there to start again")
    return None, ""


def _verdicts(project: Path, ticket: Mapping[str, Any]) -> list[str]:
    """One line a gate, then every MEDIUM finding: what she would otherwise have to
    open four files to see."""
    verdicts = ticket.get("verdicts") or {}
    if not verdicts:
        return []
    lines = ["## What the gates found", ""]
    for name in ticket.get("gates") or verdicts:
        verdict = verdicts.get(name) or {}
        counts = ", ".join(f"{verdict[key]} {key}" for key in COUNTS if verdict.get(key))
        lines.append(f"- **{name}**: {verdict.get('result', '?')}"
                     + (f" ({counts})" if counts else ""))
    mediums = []
    for name in ticket.get("gates") or verdicts:
        text = tickets.on_branch(project, ticket, f"gates/{name}.md")
        if not text:
            continue
        mediums += [f"- {f['rule']} ({f['severity']}): {f['message']}"
                    for f in gates.parse_verdict(text)["findings"]
                    if f.get("severity") == "MEDIUM"]
    if mediums:
        lines += ["", "For you to look at (never fixed automatically):", "", *mediums]
    return [*lines, ""]



