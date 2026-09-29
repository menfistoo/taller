"""What the work has cost: by ticket, by week, by model (spec 12, 7.5).

`weighted_tokens` is the figure that means something in both worlds. On a
subscription the binding limit is a usage window, so the weighted count is how
hard a ticket leaned on it; on `api` it stands in for money, and only there is
money shown at all - a dollar figure for a flat fee would be fiction (5.2).

Nothing here is estimated and nothing is stored: every number is read from the
`spend` block `spend.fold` left on each ticket's `status.yml`.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from taller import billing, config, spend, tickets

from . import reading

# A page shows the work that cost something, not every ticket ever opened.
TICKETS_SHOWN = 50
WEEKS_SHOWN = 12
FIELDS = spend.FIELDS


def figures() -> dict[str, Any]:
    """Every ticket that has spent anything, and the same spend three ways."""
    cfg = config.load_hub_config()
    weights = cfg.get("weights") or {}
    mode = billing.mode(cfg)
    show_cost = mode == "api"

    rows: list[dict[str, Any]] = []
    by_model: dict[str, dict[str, int]] = {}
    unreadable: list[dict[str, str]] = []

    # `project_entries`, not `projects`: the tickets are read once, below.
    for entry in reading.project_entries():
        if not entry["available"]:
            unreadable.append({"name": entry["name"], "problem": entry["problem"]})
            continue
        path = Path(entry["path"])
        listed, _ = tickets.list_tickets(path)
        for ticket in listed:
            row = _row(entry["name"], ticket, cfg, weights, show_cost)
            if row is None:
                continue
            rows.append(row)
            for model, tokens in (ticket["spend"].get("by_model") or {}).items():
                into = by_model.setdefault(model, {field: 0 for field in FIELDS})
                for field in FIELDS:
                    into[field] += int(tokens.get(field, 0) or 0)

    rows.sort(key=lambda row: (-row["weighted"], row["project"], row["id"]))
    models = [{"model": model, **tokens,
               "weighted": spend.weighted({model: tokens}, weights)}
              for model, tokens in by_model.items()]
    models.sort(key=lambda row: -row["weighted"])
    limits = cfg.get("budget") or {}
    return {
        "mode": mode,
        "show_cost": show_cost,
        "tickets": rows[:TICKETS_SHOWN],
        "cut": max(0, len(rows) - TICKETS_SHOWN),
        "weeks": _weeks(rows, show_cost)[:WEEKS_SHOWN],
        "models": models,
        "totals": {
            "weighted": sum(row["weighted"] for row in rows),
            "total": sum(row["total"] for row in rows),
            "cost": round(sum(row["cost"] or 0 for row in rows), 4) if show_cost else None,
            "tickets": len(rows),
        },
        # One unpriced or unattributed dispatch makes every total above it a
        # lower bound, and saying so is the difference between a figure and a lie.
        "partial": any(row["partial"] for row in rows),
        "warn_at": int(limits.get("per_ticket_warn", 400_000)),
        "stop_at": int(limits.get("per_ticket_stop", 1_200_000)),
        "unreadable": unreadable,
    }


def _row(project_name: str, ticket: dict[str, Any], cfg: dict[str, Any],
         weights: dict[str, Any], show_cost: bool) -> dict[str, Any] | None:
    """One ticket's line, or None when it has spent nothing.

    A closed ticket keeps its line: what it cost is still what it cost.
    """
    block = ticket.get("spend") or {}
    models = block.get("by_model") or {}
    if not models and not block.get("weighted_tokens"):
        return None
    # The recorded figure, not a fresh one: it is what `spend.budget` compares
    # against, and a page that disagreed with the budget would be worse than
    # one that lags a change of weights.
    weighted = int(block.get("weighted_tokens") or spend.weighted(models, weights))
    cost, unpriced = billing.cost(models, cfg) if show_cost else (None, False)
    return {
        "project": project_name,
        "id": int(ticket["id"]),
        "title": ticket["title"],
        "url": f"/ticket/{project_name}/{int(ticket['id'])}",
        "label": tickets._label(ticket["stage"]),
        "created": str(ticket.get("created") or ""),
        "weighted": weighted,
        "total": int(block.get("total_tokens") or 0),
        "cost": cost,
        "partial": bool(block.get("partial")) or unpriced,
        "budget": spend.budget(ticket, cfg),
    }


def _weeks(rows: list[dict[str, Any]], show_cost: bool) -> list[dict[str, Any]]:
    """Newest week first. A ticket belongs to the week it was OPENED.

    `status.yml` keeps a running total, not a log: there is no honest way to say
    which week a given token was spent, and the page says as much.
    """
    weeks: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = _week_of(row["created"])
        if name is None:
            continue
        week = weeks.setdefault(name, {"week": name, "weighted": 0, "cost": 0.0,
                                       "tickets": 0})
        week["weighted"] += row["weighted"]
        week["cost"] += row["cost"] or 0
        week["tickets"] += 1
    ordered = sorted(weeks.values(), key=lambda week: week["week"], reverse=True)
    for week in ordered:
        week["cost"] = round(week["cost"], 4) if show_cost else None
    return ordered


def _week_of(created: str) -> str | None:
    try:
        year, number, _ = date.fromisoformat(created[:10]).isocalendar()
    except ValueError:
        return None
    return f"{year}-W{number:02d}"
