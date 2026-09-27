"""`taller resolve`: regenerate a project's three main-side files (spec 4.6).

The fix `doctor` names for a stale or modified snapshot. A command, not an
agent: resolution is deterministic, so there is nothing to reason about.
"""

from __future__ import annotations

from typing import Any

from .. import generated, gitio, registry
from ..prompter import Prompter
from .common import project_path


def run(args: Any, prompter: Prompter) -> int:
    project = project_path(getattr(args, "path", None))
    entry = registry.get_project(project)            # a clear error if unregistered
    gitio.ensure_main_worktree(project)
    sync = generated.refresh(project)
    prompter.say(f"Resolved {entry['name']}: resolved.json, 00-index.md and brand "
                 f"tokens are current on main (sync: {sync}).")
    return 0
