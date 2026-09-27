"""`taller resolve`: regenerate a project's three main-side files (spec 4.6).

The fix `doctor` names for a stale or modified snapshot. A command, not an
agent: resolution is deterministic, so there is nothing to reason about.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .. import generated, gitio, registry
from ..prompter import Prompter


def _here() -> Path:
    completed = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace")
    return Path(completed.stdout.strip()) if completed.returncode == 0 else Path.cwd()


def run(args: Any, prompter: Prompter) -> int:
    project = Path(args.path) if getattr(args, "path", None) else _here()
    entry = registry.get_project(project)            # a clear error if unregistered
    gitio.ensure_main_worktree(project)
    sync = generated.refresh(project)
    prompter.say(f"Resolved {entry['name']}: resolved.json, 00-index.md and brand "
                 f"tokens are current on main (sync: {sync}).")
    return 0
