"""Installing Taller brings what its own test check runs (found on GitHub, 2026-10-16).

CI installs Taller and runs its gates; the tests gate runs pytest. Kept as a
`dev` extra, pytest was missing on GitHub's machine, so the gate could not run
and every full push was refused - the earlier green runs had only ever seen
ticket files.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_installing_taller_brings_pytest():
    project = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text("utf-8"))

    assert any(dep.replace(" ", "").lower().startswith("pytest")
               for dep in project["project"]["dependencies"])
