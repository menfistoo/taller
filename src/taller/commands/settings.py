"""`taller settings [show|set|edit]` (spec 5.2)."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from .. import hub, paths, settings
from ..prompter import Prompter


def open_editor(path: Path) -> None:
    """$VISUAL or $EDITOR, else the platform's plain editor. A seam for tests."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or (
        "notepad" if sys.platform == "win32" else "vi")
    subprocess.run([*shlex.split(editor, posix=sys.platform != "win32"), str(path)])


def _project(args: Any) -> Path | None:
    return Path(args.project).resolve() if getattr(args, "project", None) else None


def _touched(prompter: Prompter, touched: list[tuple[str, str]]) -> None:
    if touched:
        prompter.say("Refreshed: " + ", ".join(f"{name} ({sync})" for name, sync in touched))


def run(args: Any, prompter: Prompter) -> int:
    action = getattr(args, "action", None) or "show"
    project = _project(args)
    if action == "show":
        prompter.say(settings.render(settings.effective(project)))
        return 0
    if action == "set":
        _touched(prompter, settings.set_value(args.key, args.value, project))
        prompter.say(f"Set {args.key}.")
        return 0
    # edit
    if project is None:
        hub.ensure_repo()
        target = paths.hub_config()
        if not target.exists():
            target.write_text("# Hub settings. `taller settings` shows every key.\n",
                              encoding="utf-8")
    else:
        target = paths.project_config(project)
    open_editor(target)
    _touched(prompter, settings.after_edit(project))
    return 0
