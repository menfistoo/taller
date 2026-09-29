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

from taller import registry, tickets
from taller.errors import TallerError

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
