"""What the cockpit's screens read (spec 12). Nothing here writes.

Every figure comes from where the CLI keeps it: the registry, each project's
`status.yml` on `main`, the verdict files on the branch, and git. No database,
and no cache - a page is cheap and a stale board is worse than a slow one.

One project's trouble is its own: a folder that has moved is reported beside its
name and every other project still renders.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from taller import gates, registry, tickets
from taller.errors import ConfigError, TallerError
from taller.gates import diff as gate_diff

# What a browser is sent of any one paper, and how many changed files are listed.
# A plan can run to thousands of lines and a change to hundreds of files; the page
# has to stay quick and say what it left out.
PAPER_MAX = 20_000
DIFF_FILES_MAX = 50
NOTES_SHOWN = 12

# `close` is not a column: a closed ticket is done with (spec 12's board is ① to ⑫,
# and the twelfth is where they leave).
COLUMNS = tuple(stage for stage in tickets.STAGES if stage != "close")


def projects() -> list[dict[str, Any]]:
    """Every adopted project, with its open tickets, whether or not it is reachable."""
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
            out.append(row)
            continue
        try:
            row["tickets"] = _tickets_of(entry["name"], path)
        except TallerError as exc:
            row.update(available=False, problem=str(exc))
        out.append(row)
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
        findings = gates.parse_verdict(text)["findings"] if text else []
        out.append({
            "gate": name,
            "result": counts.get("result", "?"),
            "counts": {key: counts.get(key, 0) for key in
                       ("blocker", "high", "medium", "low", "nit")},
            "findings": findings,
            "missing": text is None,
        })
    return out


def _diff(path: Path, ticket: dict[str, Any]) -> dict[str, Any]:
    from taller import gitio

    try:
        built = gate_diff.build(path, gitio.MAIN_BRANCH, str(ticket["branch"]))
    except RuntimeError:
        return {"files": [], "cut": False, "total": 0}
    files = [{"path": f["path"], "status": f["status"],
              "added": len(f["added"]), "removed": len(f["removed"])}
             for f in built["files"]]
    return {"files": files[:DIFF_FILES_MAX], "cut": len(files) > DIFF_FILES_MAX,
            "total": len(files)}


def _notes(path: Path, ticket: dict[str, Any]) -> list[str]:
    raw = tickets.read_main(path, f"{tickets.ticket_dir(ticket)}/notes.md") or b""
    lines = raw.decode("utf-8", errors="replace").strip().splitlines()
    return lines[-NOTES_SHOWN:]


def _waiting_on(ticket: dict[str, Any]) -> str:
    checkpoint = tickets.CHECKPOINT_AT.get(ticket["stage"])
    if checkpoint and ticket["checkpoints"].get(checkpoint) == "pending" \
            and not ticket.get("blocked"):
        return checkpoint
    return ""
