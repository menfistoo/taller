"""The hub as a git repository, and writes to its `taller.yml`.

Spec 4.0 calls `~/.taller/` versioned content, and every gate verdict records the
hub's `HEAD` (4.4.1), so the hub is a git repository from its first write. It is
local only: no remote is ever created for it without the owner saying so (13.2).
Each change the owner approves is one commit, so a brand, a profile or a
language change can be seen in history and reverted.
"""

from __future__ import annotations

from typing import Any, Mapping

import yaml

from . import config, gitio, locking, paths
from .errors import ConfigError


# The registry is not versioned. Its paths are absolute and mean nothing on
# another machine, and it changes on every registration: versioned, adding one
# project would move the hub's HEAD and mark every other project's snapshot stale
# (spec 4.6) although no rule had changed. The hub's history is its rules.
GITIGNORE = (
    "# Machine-local: absolute paths, rewritten on every registration.\n"
    "projects.json\n"
)


def ensure_repo() -> None:
    """`~/.taller` as a git repository on `main`. Idempotent."""
    root = paths.hub()
    root.mkdir(parents=True, exist_ok=True)
    if not (root / ".git").exists():
        gitio.git(root, "init", "--quiet", "-b", gitio.MAIN_BRANCH)
    ignore = root / ".gitignore"
    if not ignore.exists():
        locking.atomic_write_text(ignore, GITIGNORE)


def commit(message: str) -> bool:
    """Commit every hub change. False when there was nothing to commit."""
    with locking.hub_lock():
        ensure_repo()
        root = paths.hub()
        gitio.git(root, "add", "--all")
        if gitio.git(root, "diff", "--cached", "--quiet", check=False).returncode == 0:
            return False
        gitio.git(root, "commit", "--quiet", "-m", message)
        return True


def read_config() -> dict[str, Any]:
    """The hub `taller.yml` as written — not merged with the shipped defaults."""
    path = paths.hub_config()
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping.")
    return data


def update_config(changes: Mapping[str, Any]) -> None:
    """Deep-merge `changes` into the hub `taller.yml`, keeping every other key."""
    with locking.hub_lock():
        merged = config.deep_merge(read_config(), dict(changes))
        locking.atomic_write_text(
            paths.hub_config(),
            yaml.safe_dump(merged, allow_unicode=True, sort_keys=False),
        )
