"""The Settings screen: every effective key and the layer it came from (spec 5.2).

Configuration is resolved from three files, and must be read and changed from one
place. That place is `taller settings`; this is the same list, from the same
library call, and one write that is `settings.set_value` and nothing else - so a
value changed here and a value changed in a terminal are the same value, written
to the same layer, under the same lock.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from taller import billing, config, registry, settings

from . import reading

# Spec 12: the Settings screen "hides `pricing` and `cost` entirely when the mode
# is not `api`". A price table is meaningless on a flat fee, and showing one
# invites her to tune a number that decides nothing.
MONEY_KEYS = ("pricing", "cost")


def rows(project_name: str | None = None) -> dict[str, Any]:
    """Every effective key for the hub, or for one project's own layer."""
    project = _path(project_name)
    cfg = config.load_hub_config()
    mode = billing.mode(cfg)
    show_money = mode == "api"
    listed = [
        {"key": key, "value": value, "source": source, "shown": _shown(value)}
        for key, value, source in settings.effective(project)
        if show_money or key.split(".")[0] not in MONEY_KEYS
    ]
    return {
        "rows": listed,
        "project": project_name or "",
        "projects": [entry["name"] for entry in reading.projects() if entry["available"]],
        "mode": mode,
        "show_money": show_money,
        "mismatch": billing.mismatch() or "",
    }


def save(key: str, raw: str, project_name: str | None) -> list[str]:
    """Write one key, and say what it reached. Refusals are the library's own."""
    refreshed = settings.set_value(key.strip(), raw, _path(project_name))
    where = f"{project_name}'s own settings" if project_name else "the hub"
    lines = [f"Changed {key.strip()} in {where}."]
    lines += [f"  refreshed {name} (sync: {sync})" for name, sync in refreshed]
    if not refreshed:
        lines.append("  No adopted project uses it yet.")
    return lines


def _path(project_name: str | None) -> Path | None:
    """The project's folder, or None for the hub. A name nobody knows is refused
    here rather than silently writing to the hub instead."""
    if not project_name:
        return None
    return Path(reading.entry_for(project_name)["path"])


def _shown(value: Any) -> str:
    """The value as she would type it back: YAML, because that is what it is."""
    return yaml.safe_dump(value, default_flow_style=True, allow_unicode=True).strip()
