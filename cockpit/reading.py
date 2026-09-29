"""What the cockpit's screens read (spec 12). Nothing here writes.

Every figure comes from where the CLI keeps it: the registry, each project's
`status.yml` on `main`, the verdict files on the branch, and git. No database,
and no cache - a page is cheap and a stale board is worse than a slow one.

One project's trouble is its own: a folder that has moved is reported beside its
name and every other project still renders.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml

from taller import gates, prs, registry, tickets
from taller.errors import ConfigError, TallerError
from taller.gates import diff as gate_diff

# What a browser is sent of any one paper, and how many changed files are listed.
# A plan can run to thousands of lines and a change to hundreds of files; the page
# has to stay quick and say what it left out.
PAPER_MAX = 20_000
DIFF_FILES_MAX = 50
FINDINGS_SHOWN = 25
NOTES_SHOWN = 12

# `close` is not a column: a closed ticket is done with (spec 12's board is ① to ⑫,
# and the twelfth is where they leave).
COLUMNS = tuple(stage for stage in tickets.STAGES if stage != "close")


def project_entries() -> list[dict[str, Any]]:
    """Every adopted project and whether it can be read - and NOT its tickets.

    Most screens want a name and a path. Reading every ticket of every project to
    print a name costs two git calls per ticket, which made the pages that show
    no ticket at all as slow as the board.
    """
    out: list[dict[str, Any]] = []
    try:
        entries = registry.list_projects()
    except TallerError as exc:
        return [{"name": "the registry", "path": "", "available": False,
                 "problem": str(exc), "tickets": []}]
    for entry in entries:
        if not registry.is_adopted(entry):
            continue
        path = Path(entry["path"])
        row: dict[str, Any] = {"name": entry["name"], "path": str(path),
                               "profile": entry.get("profile", ""), "available": True,
                               "problem": "", "tickets": []}
        if not path.is_dir():
            row.update(available=False,
                       problem=f"its folder is not there any more ({path}). Move it back, or "
                               f"`taller project discover` to sort it out.")
        elif not (path / ".git").exists():
            # Git failing reads as "no tickets", and a project with work in it
            # being shown as empty is worse than being shown as unreadable.
            row.update(available=False,
                       problem=f"its folder is there ({path}) but there is no git repository "
                               f"in it any more, so its tickets cannot be read.")
        out.append(row)
    return out


def projects() -> list[dict[str, Any]]:
    """Every adopted project, with its open tickets, whether or not it is reachable."""
    out = project_entries()
    for row in out:
        if not row["available"]:
            continue
        try:
            row["tickets"] = _tickets_of(row["name"], Path(row["path"]))
        except TallerError as exc:
            row.update(available=False, problem=str(exc))
    return out


def board() -> list[dict[str, Any]] | dict[str, Any]:
    """The columns, stage by stage, and the projects behind them."""
    found = projects()
    everything = [ticket for project in found for ticket in project["tickets"]]
    return {
        "projects": found,
        "stages": [{"stage": stage, "label": tickets._label(stage),
                    "tickets": [t for t in everything if t["stage"] == stage]}
                   for stage in COLUMNS],
        "waiting": [t for t in everything if t["waiting_for_you"]],
        "blocked": [t for t in everything if t["blocked"]],
    }


def _tickets_of(project_name: str, path: Path) -> list[dict[str, Any]]:
    listed, unreadable = tickets.list_tickets(path)
    out = []
    for ticket in listed:
        if ticket.get("stage") == "close":
            continue
        out.append(_row(project_name, path, ticket))
    out += [{"project": project_name, "id": 0, "title": f"unreadable: {name}",
             "stage": "intake", "label": tickets._label("intake"), "lane": "",
             "waiting_for_you": False, "waiting_on": "", "blocked": "", "unsynced": False,
             "url": ""}
            for name in unreadable]
    return out


def _row(project_name: str, path: Path, ticket: dict[str, Any]) -> dict[str, Any]:
    checkpoint = tickets.CHECKPOINT_AT.get(ticket["stage"])
    pending = bool(checkpoint) and ticket["checkpoints"].get(checkpoint) == "pending"
    blocked = (ticket.get("blocked") or {}).get("reason", "")
    # The card shows the first line: a blocked reason can carry a gate's whole
    # output, and a wall of log text on a card hides every other ticket.
    first_line = blocked.strip().splitlines()[0] if blocked.strip() else ""
    return {
        "project": project_name,
        "id": int(ticket["id"]),
        "title": ticket["title"],
        "kind": ticket.get("kind", ""),
        "stage": ticket["stage"],
        "label": tickets._label(ticket["stage"]),
        "lane": ticket.get("lane") or "",
        "waiting_for_you": pending and not blocked,
        "waiting_on": checkpoint if pending else "",
        "blocked": first_line,
        "blocked_in_full": blocked,
        "unsynced": tickets.effective_sync(path, ticket) == "pending",
        "url": f"/ticket/{project_name}/{int(ticket['id'])}",
    }


def ticket_page(project_name: str, ticket_id: int) -> dict[str, Any]:
    """Everything one ticket's page shows. Reads; never writes.

    What `main` holds - the ask, the notes, the state - is always there. The
    plan, the review and the verdicts live on the branch, so a ticket whose
    branch has been deleted (a rejection at ⑦, §7.2) still renders, with the
    branch named in `gone`.
    """
    entry = entry_for(project_name)
    path = Path(entry["path"])
    ticket = tickets.load(path, ticket_id)
    gone: list[str] = []
    branch = ticket.get("branch")
    if branch and not _branch_is_there(path, branch):
        gone.append(f"the branch {branch} is gone, so the plan, the review and the "
                    f"verdicts are not readable any more")

    papers = {name: _paper(path, ticket, name) for name in ("plan.md", "review.md")}
    return {
        "project": entry["name"],
        "ticket": ticket,
        "label": tickets._label(ticket["stage"]),
        "words": tickets._words(path, ticket).strip(),
        "plan": papers["plan.md"],
        "review": papers["review.md"],
        "verdicts": _verdicts(path, ticket),
        "diff": _diff(path, ticket) if branch and not gone else {"files": [], "cut": False,
                                                                 "total": 0},
        "notes": _notes(path, ticket),
        "waiting_on": _waiting_on(ticket),
        # Spec 12: the ticket screen shows approve / reject / change, and the pull
        # request as GitHub has it rather than only the number Taller wrote down.
        "can_change": tickets.stage_number(ticket["stage"]) <= tickets.stage_number("design")
        and not ticket.get("blocked"),
        "pr_state": _pr_state(path, ticket),
        "blocked": (ticket.get("blocked") or {}).get("reason", ""),
        "gone": gone,
    }


def entry_for(project_name: str) -> dict[str, Any]:
    """The registry's row for a project, by the name the pages use."""
    for entry in registry.list_projects():
        if entry["name"] == project_name:
            return entry
    raise ConfigError(f"No project called {project_name!r} is registered.")


def _branch_is_there(path: Path, branch: str) -> bool:
    from taller import gitio

    return gitio.git(path, "rev-parse", "--verify", "--quiet", branch,
                     check=False).returncode == 0


def _paper(path: Path, ticket: dict[str, Any], name: str) -> str | None:
    text = tickets.on_branch(path, ticket, name)
    if text is None:
        return None
    if len(text) > PAPER_MAX:
        return text[:PAPER_MAX] + f"\n\n[... cut here: {len(text) - PAPER_MAX} more "\
                                  f"characters are in {name} on the branch ...]"
    return text


def _verdicts(path: Path, ticket: dict[str, Any]) -> list[dict[str, Any]]:
    """Every gate that ran, with its counts and the findings from its verdict file."""
    out = []
    recorded = ticket.get("verdicts") or {}
    for name in ticket.get("gates") or recorded:
        counts = recorded.get(name) or {}
        text = tickets.on_branch(path, ticket, f"gates/{name}.md")
        findings, unreadable = _findings(text)
        out.append({
            "gate": name,
            "result": counts.get("result", "?"),
            "counts": {key: counts.get(key, 0) for key in
                       ("blocker", "high", "medium", "low", "nit")},
            # Capped like every other panel: the constitution gate reports one
            # finding per offending line per file, and four hundred of them was a
            # megabyte of HTML for one ticket.
            "findings": findings[:FINDINGS_SHOWN],
            "more": max(0, len(findings) - FINDINGS_SHOWN),
            "missing": text is None,
            "unreadable": unreadable,
        })
    return out


def _findings(text: str | None) -> tuple[list[dict[str, Any]], bool]:
    """A verdict file's findings, and whether the file could not be read at all.

    A file that is truncated, hand-edited or half-written is a fact about one
    gate, not a reason for her whole ticket to be a blank 500.
    """
    if text is None:
        return [], False
    try:
        return list(gates.parse_verdict(text)["findings"] or []), False
    except (ValueError, KeyError, TypeError, yaml.YAMLError):
        return [], True


def _diff(path: Path, ticket: dict[str, Any]) -> dict[str, Any]:
    """Which files changed and by how many lines - one git call, whatever the size.

    Deliberately NOT `gates.diff.build`: that reads every changed file's whole
    text and its patch, because the constitution gate needs them. A page needs
    four numbers per file, and asking for the gate's structure made a 200-file
    ticket take 26 seconds to render - which the four-second refresh then asked
    for again, for ever.
    """
    from taller import gitio

    numstat = gitio.git(path, "-c", "core.quotepath=false", "diff", "--numstat",
                        "--no-renames", f"{gitio.MAIN_BRANCH}...{ticket['branch']}",
                        check=False)
    if numstat.returncode != 0:
        return {"files": [], "cut": False, "total": 0,
                "problem": "git could not say what changed on the branch"}
    files = []
    for line in numstat.stdout.splitlines():
        added, _, rest = line.partition("\t")
        removed, _, name = rest.partition("\t")
        # `.taller/work/` is Taller's own bookkeeping, not her change (spec 10.2).
        if not name or name.startswith(gate_diff.IGNORED):
            continue
        # A binary file's counts are given as `-`, and are not numbers.
        files.append({"path": name, "added": _count(added), "removed": _count(removed),
                      "binary": added == "-"})
    return {"files": files[:DIFF_FILES_MAX], "cut": len(files) > DIFF_FILES_MAX,
            "total": len(files), "problem": ""}


def _count(field: str) -> int:
    return int(field) if field.isdigit() else 0


def _notes(path: Path, ticket: dict[str, Any]) -> list[str]:
    raw = tickets.read_main(path, f"{tickets.ticket_dir(ticket)}/notes.md") or b""
    lines = raw.decode("utf-8", errors="replace").strip().splitlines()
    return lines[-NOTES_SHOWN:]


# GitHub's answer about one pull request, kept for a few seconds. The ticket page
# refreshes itself every four seconds while a run is going, and a round-trip to
# someone else's network on every one of those is a page that blocks on it.
PR_STATE_SECONDS = 20.0
_pr_states: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}


def _pr_state(path: Path, ticket: dict[str, Any]) -> dict[str, Any]:
    number = ticket.get("pr")
    if not number:
        return prs.state(path, ticket)          # asks nothing without a number
    key = (str(path), int(number))
    asked_at, kept = _pr_states.get(key, (0.0, {}))
    if kept and time.monotonic() - asked_at < PR_STATE_SECONDS:
        return kept
    state = prs.state(path, ticket)
    _pr_states[key] = (time.monotonic(), state)
    return state


def _waiting_on(ticket: dict[str, Any]) -> str:
    checkpoint = tickets.CHECKPOINT_AT.get(ticket["stage"])
    if checkpoint and ticket["checkpoints"].get(checkpoint) == "pending" \
            and not ticket.get("blocked"):
        return checkpoint
    return ""
