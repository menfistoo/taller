"""What it uses: which Claude does each job, and where her plan went.

Read from what the work recorded (`spend.ran`, `spend.by_role`), not from the
configuration, which only says what was asked for: a fallback, or a model she
switched since, is shown as it happened. Written through `settings.set_value`
on the hub, exactly as `taller settings set` writes it.
"""

from __future__ import annotations

import re
from pathlib import Path
from statistics import median
from typing import Any, Mapping

from taller import config, settings, spend, tickets
from taller.errors import ConfigError

from . import reading, words

# Each job she sees, and the roles that do it; the first is the one named.
JOB_ROLES = (
    ("understanding", ("chief",)),
    ("reading", ("explorer",)),
    ("planning", ("architect",)),
    ("changing", ("implementer", "fixer")),
    ("checking", ("gate_quality", "gate_ux", "gate_security")),
    ("summarising", ("summariser", "scribe")),
)
# The two jobs the strongest model is offered for, and the role each writes.
STRONGEST = {"plans": "architect", "safety": "gate_security"}
STRONGEST_ALIAS, USUAL_ALIAS = "creative", "thinker"
_DATED = re.compile(r"-\d{8}$")


def usage() -> dict[str, Any]:
    cfg = config.load_hub_config()
    listed = _all_tickets()
    return {
        "jobs": [_job(key, roles, listed, cfg) for key, roles in JOB_ROLES],
        "strongest": {job: (cfg.get("models") or {}).get(role) == STRONGEST_ALIAS
                      for job, role in STRONGEST.items()},
        "strongest_name": model_name("fable"),
        "things": _things(listed),
        "leave_out": bool((cfg.get("dispatch") or {}).get("leave_out_my_setup", True)),
    }


def choose_strongest(for_job: str, on: bool) -> list[str]:
    """The strongest model for writing plans, or for checking safety - or back."""
    role = STRONGEST.get(for_job)
    if role is None:
        raise ConfigError(words.USAGE["not_offered"])
    settings.set_value(f"models.{role}", STRONGEST_ALIAS if on else USUAL_ALIAS)
    return [words.USAGE["saved"]]


def leave_out(on: bool) -> list[str]:
    """Task 1's switch: her connected services and plugins out of every job."""
    settings.set_value("dispatch.leave_out_my_setup", "true" if on else "false")
    return [words.USAGE["saved"]]


def model_name(model: str) -> str:
    """`claude-haiku-4-5-20251001` -> `Claude Haiku 4.5`; a CLI alias -> today's model."""
    known = words.MODEL_FOR_ALIAS.get(model)
    if known:
        return known
    parts = _DATED.sub("", model).split("-")
    named = [part.capitalize() for part in parts if not part.isdigit()]
    version = ".".join(part for part in parts if part.isdigit())
    return " ".join(named + ([version] if version else []))


def _all_tickets() -> list[tuple[str, dict[str, Any]]]:
    found = []
    for entry in reading.project_entries():
        if not entry.get("available"):
            continue
        listed, _ = tickets.list_tickets(Path(entry["path"]))
        found += [(entry["name"], ticket) for ticket in listed]
    return sorted(found, key=lambda pair: str(pair[1].get("created") or ""), reverse=True)


def _ran(role: str, listed: list[tuple[str, dict[str, Any]]], cfg: Mapping[str, Any]) -> str:
    """The model this role last ran on, newest thing first; else the one it will use."""
    for _, ticket in listed:
        model = ((ticket.get("spend") or {}).get("ran") or {}).get(role)
        if model:
            return model_name(str(model))
    return model_name(config.resolve_model(role, cfg))


def _job(key: str, roles: tuple[str, ...], listed: list[tuple[str, dict[str, Any]]],
         cfg: Mapping[str, Any]) -> dict[str, str]:
    model = _ran(roles[0], listed, cfg)
    extra = ""
    if "gate_security" in roles:
        safety = _ran("gate_security", listed, cfg)
        if safety != model:
            extra = words.USAGE["for_safety"].format(model=safety.removeprefix("Claude "))
    return {"name": words.JOBS[key], "model": model,
            "note": words.MODEL_NOTES.get(model, ""), "extra": extra}


def _things(listed: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Everything that used some of her plan, biggest first, against the biggest."""
    used = [(name, ticket, int((ticket.get("spend") or {}).get("weighted_tokens") or 0))
            for name, ticket in listed]
    used = [row for row in used if row[2] > 0]
    if not used:
        return []
    largest = max(amount for _, _, amount in used)
    usual = median(amount for _, _, amount in used)
    return [{"title": ticket["title"], "project": name,
             "width": max(2, round(amount * 100 / largest)),
             "more": len(used) > 2 and amount > 2 * usual,
             "where": _where(ticket)}
            for name, ticket, amount in sorted(used, key=lambda row: row[2], reverse=True)]


def _where(ticket: Mapping[str, Any]) -> str:
    """Where most of it went, by job - or nothing, for a thing recorded before jobs
    were counted: a guess would read as a fact."""
    by_role = (ticket.get("spend") or {}).get("by_role")
    if not by_role:
        return ""
    weights = config.load_hub_config().get("weights") or {}
    totals = {key: sum(spend.weighted({role: by_role[role]}, weights)
                       for role in roles if role in by_role)
              for key, roles in JOB_ROLES}
    top = max(totals, key=lambda key: totals[key])
    return words.WHERE[top] if totals[top] > 0 else ""
