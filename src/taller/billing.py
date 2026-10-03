"""How Claude is paid for, and what spend costs in money when that is meaningful.

Spec 5.2: the mode is detected from the environment and may be overridden. On a
subscription the binding limit is a usage window, not money, so a dollar figure
would be fiction: `cost` is computed only when the mode is `api` (7.5). The
price table ships dated, and its age is reported rather than trusted.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Mapping

from . import config, hub


def mode(cfg: Mapping[str, Any]) -> str:
    """The configured mode, else the detected one."""
    return (cfg.get("billing") or {}).get("mode") or config.detect_billing_mode()


def mismatch() -> str | None:
    """The sentence to show when the configured mode is not what the environment says.

    Read from the hub file itself: the merged configuration fills an unset mode
    with the detected one, so it cannot tell "configured" from "guessed".
    """
    configured = (hub.read_config().get("billing") or {}).get("mode")
    detected = config.detect_billing_mode()
    if configured and configured != detected:
        return (f"configured as {configured}, but the environment says {detected} - "
                f"e.g. an API key appeared since setup, so budgets may now mean money")
    return None


def cost(by_model: Mapping[str, Mapping[str, int]], cfg: Mapping[str, Any]
         ) -> tuple[float | None, bool]:
    """(cost in the pricing table's currency, partial) - `(None, False)` off `api`.

    Prices are per million tokens for input and output; cache writes and reads
    are priced from input by the configured weights, the same ratios §7.5 uses.
    A model the table does not price makes the figure partial - a lower bound,
    never an estimate.
    """
    if mode(cfg) != "api":
        return None, False
    pricing = cfg.get("pricing") or {}
    weights = cfg.get("weights") or {}
    total, partial = 0.0, False
    for model, tokens in by_model.items():
        price = price_of(model, pricing)
        if price is None:
            partial = True
            continue
        per_input = float(price.get("input", 0)) / 1_000_000
        per_output = float(price.get("output", 0)) / 1_000_000
        per_read = float(price["cache_read"]) / 1_000_000 if "cache_read" in price \
            else per_input * float(weights.get("cache_read", 0.1))
        total += tokens.get("input", 0) * per_input
        total += tokens.get("cache_write", 0) * per_input * float(weights.get("cache_write", 1.25))
        total += tokens.get("cache_read", 0) * per_read
        total += tokens.get("output", 0) * per_output
    return round(total, 4), partial


_DATED = re.compile(r"-\d{8}$")


def price_of(model: str, pricing: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """A model's price, or None. A dated id (`claude-haiku-4-5-20251001`) is the
    same model as its undated name, which is how the table lists it."""
    price = pricing.get(model)
    if not isinstance(price, Mapping):
        price = pricing.get(_DATED.sub("", model))
    return price if isinstance(price, Mapping) else None


def pricing_age_days(cfg: Mapping[str, Any], today: date) -> int | None:
    as_of = (cfg.get("pricing") or {}).get("as_of")
    try:
        return (today - date.fromisoformat(str(as_of))).days
    except (TypeError, ValueError):
        return None
