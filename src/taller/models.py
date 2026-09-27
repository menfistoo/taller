"""Which models the account can reach, and what to use when one cannot be.

Spec 6.2: the set of available models cannot be listed from Claude Code, so
`taller models probe` asks each candidate a trivial question and records what
answered. Gates and `doctor` read the record; they never probe on their own,
because a probe is inference and inference spends the owner's usage window.

Spec 14: a model that is unavailable mid-ticket degrades to `fallback` rather
than crashing, and the substitution is recorded.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from . import config, inference, locking, paths

CANDIDATES = ("opus", "sonnet", "haiku", "fable")
PROBE_TIMEOUT = 120.0


def probe(candidates: Iterable[str] = CANDIDATES) -> dict[str, Any]:
    """One trivial dispatch per candidate; the record is written to the hub."""
    cfg = config.load_hub_config()
    record: dict[str, Any] = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "models": {},
    }
    for name in candidates:
        started = time.monotonic()
        result = inference.infer(inference.Dispatch(
            role="explorer", prompt="Reply with the single word OK.", config=cfg,
            model=name, timeout=PROBE_TIMEOUT))
        record["models"][name] = {
            "ok": bool(result.ok),
            "latency_s": round(time.monotonic() - started, 2),
            "error": None if result.ok else (result.error or "no answer"),
        }
    locking.atomic_write_text(paths.models_probe(), json.dumps(record, indent=2) + "\n")
    return record


def load_probe() -> dict[str, Any] | None:
    try:
        return json.loads(paths.models_probe().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def reachable(model: str, record: Mapping[str, Any] | None) -> bool | None:
    """True or False per the last probe; None when that model was never probed."""
    entry = ((record or {}).get("models") or {}).get(model)
    return None if entry is None else bool(entry.get("ok"))


def configured(cfg: Mapping[str, Any]) -> list[str]:
    """Every model a role or the fallback can resolve to, in a stable order."""
    names = [config.resolve_model(role, cfg) for role in cfg["models"]]
    names.append(cfg["model_aliases"][cfg["fallback"]])
    return list(dict.fromkeys(names))


def fallback_for(role: str, cfg: Mapping[str, Any]) -> str | None:
    """The model to retry on when the role's own is unavailable; None if it is the same."""
    fallback = cfg["model_aliases"][cfg["fallback"]]
    return None if fallback == config.resolve_model(role, cfg) else fallback
