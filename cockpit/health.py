"""The Health screen: what `taller scan` finds, when she asks for it (spec 9.5).

A scan reads every file in a project and runs its suite in a throwaway checkout.
That is far too much for a page load, so **no page here runs one**: the page
lists the projects with whatever the last check found, and a button runs another.

The result is kept as one small file per project under the runtime directory -
never in the hub, which is versioned, and never in the project, which is hers.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from taller import constitution, locking, paths
from taller.errors import ConfigError
from taller.commands import scan

from . import reading


def last_dir() -> Path:
    """Where the last check of each project is kept.

    A function, not a constant: `paths.run_dir()` reads the home directory when
    it is called, and a constant would pin the first one seen at import.
    """
    return paths.run_dir() / "cockpit-health"


def projects() -> list[dict[str, Any]]:
    """Every project, with its last check if it has one."""
    return [{**entry, "checked": last(entry["name"])}
            for entry in reading.project_entries()]


def last(project_name: str) -> dict[str, Any] | None:
    """The figures kept from the last check, or None when there has been none."""
    try:
        return json.loads((last_dir() / f"{project_name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def check(project_name: str) -> dict[str, Any]:
    """Scan one project now, keep what it found, and return it.

    `scan.health` writes nothing to the project: it runs the suite in a checkout
    of HEAD in a temporary folder, because her own tree may hold work in progress.
    """
    entry = reading.entry_for(project_name)
    path = Path(entry["path"])
    if not path.is_dir():
        raise ConfigError(f"{project_name}'s folder is not there any more ({path}), so "
                          f"there is nothing to check. Move it back, or "
                          f"`taller project discover` to sort it out.")
    began = time.monotonic()
    figures = scan.health(path, constitution.resolve(path))
    figures.update({
        "name": project_name,
        "seconds": round(time.monotonic() - began, 1),
        "when": datetime.now().isoformat(timespec="seconds"),
    })
    locking.atomic_write(last_dir() / f"{project_name}.json",
                         json.dumps(figures, indent=2).encode("utf-8"))
    return figures
