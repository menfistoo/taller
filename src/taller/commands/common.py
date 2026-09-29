"""What several commands need: which project the owner means."""

from __future__ import annotations

import subprocess
from pathlib import Path


def project_path(given: str | None) -> Path:
    """The path given, else the repository the owner is standing in."""
    if given:
        return Path(given)
    completed = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace")
    return Path(completed.stdout.strip()) if completed.returncode == 0 else Path.cwd()
