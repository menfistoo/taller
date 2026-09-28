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

import json
import re
from pathlib import Path
from typing import Any, Mapping

from . import billing, inference, locking, registry, tickets

FIELDS = ("input", "cache_write", "cache_read", "output")
# The transcript's usage names, renamed once to UsageRecord's (spec 3.6, 7.5).
TRANSCRIPT_FIELDS = {"input_tokens": "input", "cache_creation_input_tokens": "cache_write",
                     "cache_read_input_tokens": "cache_read", "output_tokens": "output"}
TRANSCRIPTS_ROOT: Path | None = None      # None: ~/.claude/projects


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
        # Taller's own dispatches: their transcripts must not be counted again.
        sessions = list(block.get("sessions") or [])
        if result.session_id and result.session_id not in sessions:
            sessions.append(result.session_id)
        block["sessions"] = sessions
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


def transcript_slug(path: Path) -> str:
    """Claude Code's folder name for a working directory: non-alphanumerics -> "-"."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def from_transcripts(project: Path | str, ticket: Mapping[str, Any], *,
                     root: Path | None = None) -> dict[str, dict[str, int]]:
    """What chats spent on the ticket's branch - work Taller did not dispatch (7.5).

    Read from the transcripts of the project checkout and the ticket's worktree;
    Taller's own dispatches (their session ids are in `spend.sessions`) and every
    repeat of one message (Claude Code writes a line per content block) are left
    out. A line that does not parse is skipped. Nothing is written.
    """
    branch = ticket.get("branch")
    if not branch:
        return {}
    root = root or TRANSCRIPTS_ROOT or Path.home() / ".claude" / "projects"
    places = [Path(project)]
    try:
        places.append(tickets._worktree(Path(project), ticket))
    except Exception:
        pass                                  # no worktree to look for: the checkout only
    known = set((ticket.get("spend") or {}).get("sessions") or [])
    seen: set[str] = set()
    by_model: dict[str, dict[str, int]] = {}
    for place in places:
        folder = root / transcript_slug(place)
        for transcript in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
            for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
                _count(line, branch, known, seen, by_model)
    return by_model


def _count(line: str, branch: str, known: set[str], seen: set[str],
           by_model: dict[str, dict[str, int]]) -> None:
    try:
        entry = json.loads(line)
    except ValueError:
        return
    if not isinstance(entry, dict) or entry.get("type") != "assistant" \
            or entry.get("gitBranch") != branch or entry.get("sessionId") in known:
        return
    message = entry.get("message") or {}
    usage, model, key = message.get("usage"), message.get("model"), message.get("id")
    if not isinstance(usage, dict) or not model or not key or key in seen:
        return
    seen.add(key)
    tokens = by_model.setdefault(model, {field: 0 for field in FIELDS})
    for name, field in TRANSCRIPT_FIELDS.items():
        tokens[field] += int(usage.get(name) or 0)


def budget(ticket: Mapping[str, Any], cfg: Mapping[str, Any]) -> str:
    """`ok`, `warn` past `per_ticket_warn`, `stop` past `per_ticket_stop` (7.5)."""
    spent = int((ticket.get("spend") or {}).get("weighted_tokens") or 0)
    limits = cfg.get("budget") or {}
    if spent >= int(limits.get("per_ticket_stop", 1_200_000)):
        return "stop"
    if spent >= int(limits.get("per_ticket_warn", 400_000)):
        return "warn"
    return "ok"
