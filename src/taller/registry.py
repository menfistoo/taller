"""~/.taller/projects.json — which projects Taller knows about.

Writes are serialised on registry_lock() and land through an atomic replace, so a
crash cannot leave a half-written registry (spec 10.3).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import locking, paths
from .errors import ConfigError

Project = dict[str, Any]


def _read() -> list[Project]:
    try:
        text = paths.registry().read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{paths.registry()} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ConfigError(f"{paths.registry()} must contain a list of projects.")
    return data


def list_projects() -> list[Project]:
    return _read()


def get_project(path: Path | str) -> Project:
    wanted = str(Path(path).resolve())
    for project in _read():
        if project["path"] == wanted:
            return project
    raise ConfigError(
        f"{wanted} is not registered. Run `taller project adopt` in it first."
    )


def add_project(*, path: Path | str, name: str, profile: str, brand: str | None) -> Project:
    """Add or update by resolved path. Idempotent, so re-adopting is safe."""
    resolved = str(Path(path).resolve())
    entry: Project = {
        "path": resolved,
        "name": name,
        "profile": profile,
        "brand": brand,
        "last_seen": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with locking.registry_lock():
        projects = [p for p in _read() if p["path"] != resolved]
        projects.append(entry)
        projects.sort(key=lambda p: p["name"])
        locking.atomic_write_text(
            paths.registry(), json.dumps(projects, indent=2) + "\n"
        )
    return entry


def remove_project(path: Path | str) -> None:
    resolved = str(Path(path).resolve())
    with locking.registry_lock():
        projects = [p for p in _read() if p["path"] != resolved]
        locking.atomic_write_text(
            paths.registry(), json.dumps(projects, indent=2) + "\n"
        )


def missing_paths() -> list[str]:
    """Registered paths that no longer exist. `taller doctor` fails on these."""
    return [p["path"] for p in _read() if not Path(p["path"]).is_dir()]
