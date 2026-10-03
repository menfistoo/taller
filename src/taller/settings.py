"""Settings: one place to read and change configuration (spec 5.2).

Configuration resolves from three files (chain 1, spec 4.4) but is read and
changed here: every effective key, its value, and the layer it came from. A
change is written to the right layer and then **fans out** - a hub change moves
the hub's HEAD, which makes every snapshot stale until it is refreshed (4.6), so
this module refreshes them rather than leaving `doctor` to discover it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import yaml

from . import catalogue, config, constitution, generated, gitio, hub, locking, paths, registry
from .errors import ConfigError

Row = tuple[str, Any, str]                  # dotted key, value, layer

# Informational or generated; not settings anyone should set.
HIDDEN = {"hub_sha"}


def _leaves(data: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(data, dict) and data:
        for key, value in data.items():
            yield from _leaves(value, f"{prefix}{key}.")
    else:
        yield prefix.rstrip("."), data


def _has(data: Any, dotted: str) -> bool:
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return False
        data = data[part]
    return True


def layers(project: Path | None = None) -> list[tuple[str, dict[str, Any]]]:
    """Chain 1's layers, lowest first, each as written."""
    chain: list[tuple[str, dict[str, Any]]] = [
        ("default", config.SHIPPED_DEFAULTS), ("hub", hub.read_config())]
    if project is not None:
        entry = registry.get_project(project)
        profile = catalogue.read_hub_profile(entry["profile"])
        chain.append((f"profile {entry['profile']}", {
            key: value for key, value in profile.items()
            if key not in constitution.PROFILE_NON_CONFIG_KEYS}))
        chain.append(("project", config.read_project_config(project)))
    return chain


def effective(project: Path | None = None) -> list[Row]:
    """Every effective key, its value, and the layer that last set it."""
    chain = layers(project)
    merged: dict[str, Any] = {}
    for _, data in chain:
        merged = config.deep_merge(merged, data)
    rows: list[Row] = []
    for key, value in _leaves(merged):
        if key.split(".")[0] in HIDDEN:
            continue
        source = next((name for name, data in reversed(chain) if _has(data, key)), "default")
        if key == "billing.mode" and value is None:
            value, source = config.detect_billing_mode(), "detected"
        rows.append((key, value, source))
    return rows


def render(rows: list[Row]) -> str:
    width = max((len(key) for key, _, _ in rows), default=0)
    return "\n".join(f"  {key:<{width}}  {yaml.safe_dump(value, default_flow_style=True).strip()}"
                     f"   ({source})" for key, value, source in rows)


def set_value(key: str, raw: str, project: Path | None = None) -> list[tuple[str, str]]:
    """Write one key to the hub, or to `project`'s own file. Returns what was refreshed.

    The value is YAML, so `400`, `true` and `[a, b]` arrive typed. A key no layer
    knows is refused - a typo would otherwise be a setting nothing reads. An
    append-only key cannot lose an entry (spec 4.4).
    """
    try:
        value = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{raw!r} is not a value: {exc}") from exc
    known = {row[0] for row in effective(project)}
    if key not in known and not any(k.startswith(key + ".") for k in known) \
            and key.split(".")[0] not in config.OPEN_MAPS:
        raise ConfigError(f"There is no setting {key!r}. `taller settings` lists them all.")

    parts = key.split(".")
    change: dict[str, Any] = value
    for part in reversed(parts):
        change = {part: change}

    if tuple(parts) in config.APPEND_ONLY_LIST_PATHS:
        target = config.read_project_config(project) if project else hub.read_config()
        current = target
        for part in parts:
            current = current.get(part, {}) if isinstance(current, dict) else {}
        current = current or []
        if not isinstance(value, list) or [item for item in current if item not in value]:
            raise ConfigError(f"{key} is append-only (spec 4.4): a value may be added, "
                              f"never removed. It currently holds {current}.")

    if project is None:
        hub.update_config(change)
        hub.commit(f"settings: {key}")
        return generated.refresh_affected(everything=True, message=f"taller: resolve after {key}")

    project = Path(project)
    gitio.require_clean_main(project, "`taller settings set --project`")
    with locking.project_lock(registry.get_project(project)["name"]):
        merged = config.deep_merge(config.read_project_config(project), change)
        locking.atomic_write_text(paths.project_config(project),
                                  yaml.safe_dump(merged, allow_unicode=True, sort_keys=False))
    gitio.git(project, "add", "--", ".taller/taller.yml")
    gitio.git(project, "commit", "--quiet", "-m", f"settings: {key}")
    return [(registry.get_project(project)["name"], generated.refresh(project))]


def after_edit(project: Path | None = None) -> list[tuple[str, str]]:
    """Validate a hand-edited file, then commit and fan out as `set_value` does."""
    effective(project)                       # raises ConfigError on broken YAML
    if project is None:
        hub.commit("settings: edited by hand")
        return generated.refresh_affected(everything=True)
    project = Path(project)
    if gitio.git(project, "status", "--porcelain", "--", ".taller/taller.yml").stdout.strip():
        gitio.git(project, "add", "--", ".taller/taller.yml")
        gitio.git(project, "commit", "--quiet", "-m", "settings: edited by hand")
    return [(registry.get_project(project)["name"], generated.refresh(project))]
