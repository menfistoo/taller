"""Spend: every dispatch's usage folded into its ticket, weighted, against a budget.

Spec 7.5. `Result.usage` is the authoritative source and `status.yml` is the
store: `fold` merges a dispatch's records into `spend.by_model` at completion,
under the project lock, so there is no separate log for records to be lost from.

`by_model` is keyed by the model id the run reported, never an alias, so the
record stays truthful when an alias is remapped or a fallback fires. A resumed
session's `cost_usd` is the whole conversation's running total - summing it
across the chief's stages would multiply the chief's spend - so it is ignored;
cost, when there is one, is computed from usage. Spend is never estimated: a
dispatch that reported no usage marks the figure `partial`, a lower bound.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from . import billing, inference, locking, registry, tickets

FIELDS = ("input", "cache_write", "cache_read", "output")


def weighted(by_model: Mapping[str, Mapping[str, int]], weights: Mapping[str, float]) -> int:
    """Σ over models Σ over fields (tokens × weight), rounded (7.5)."""
    return round(sum(tokens.get(field, 0) * float(weights.get(field, 1.0))
                     for tokens in by_model.values() for field in FIELDS))


def fold(project: Path | str, ticket_id: int, result: inference.Result,
         cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Add one dispatch's usage to the ticket and return the new spend block."""
    with locking.project_lock(registry.get_project(project)["name"]):
        ticket = tickets.load(project, ticket_id)
        block = dict(ticket.get("spend") or {})
        by_model = {model: dict(tokens) for model, tokens in (block.get("by_model") or {}).items()}
        for record in result.usage:
            tokens = by_model.setdefault(record.model, {field: 0 for field in FIELDS})
            for field in FIELDS:
                tokens[field] = tokens.get(field, 0) + int(getattr(record, field, 0) or 0)
        partial = bool(block.get("partial")) or (result.ok and not result.usage)
        cost, unpriced = billing.cost(by_model, cfg)
        block.update({
            "by_model": by_model,
            "total_tokens": sum(sum(tokens.get(f, 0) for f in FIELDS)
                                for tokens in by_model.values()),
            "weighted_tokens": weighted(by_model, cfg.get("weights") or {}),
            "cost": cost,
            "partial": partial or unpriced,
        })
        ticket["spend"] = block
        tickets.write(project, ticket, f"ticket {int(ticket_id):04d}: spend")
        return block


def budget(ticket: Mapping[str, Any], cfg: Mapping[str, Any]) -> str:
    """`ok`, `warn` past `per_ticket_warn`, `stop` past `per_ticket_stop` (7.5)."""
    spent = int((ticket.get("spend") or {}).get("weighted_tokens") or 0)
    limits = cfg.get("budget") or {}
    if spent >= int(limits.get("per_ticket_stop", 1_200_000)):
        return "stop"
    if spent >= int(limits.get("per_ticket_warn", 400_000)):
        return "warn"
    return "ok"
