"""The tests gate: the project's own suite ran, and passed (spec 9.1, 9.7).

`pytest` runs as a subprocess in the worktree, under the project's interpreter
when it has a `venv/` or `.venv/`, else under Taller's own. A suite that could
not run - a broken conftest, a missing interpreter, a timeout, any exit pytest
reserves for "I could not do what you asked" - is `result: error`, which the
chief escalates (`gates.errors`) and never mistakes for a pass (Review Focus 1).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from taller import inference
from taller.gates import Finding, Verdict, finding, verdict

GATE = "tests"
TIMEOUT_S = 600
TAIL_LINES = 40
ARGS = ["-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfE"]
_OUTCOME = re.compile(r"(\d+) (passed|failed|error|errors)\b")
_FAILED = re.compile(r"^(?:FAILED|ERROR) (\S+?)(?: - .*)?$", re.MULTILINE)
_TOTAL = re.compile(r"^TOTAL\s.*?(\d+(?:\.\d+)?)%\s*$", re.MULTILINE)


def run(worktree: Path | str, ruleset: Mapping[str, Any], *,
        project: Path | str | None = None, timeout_s: float = TIMEOUT_S,
        only: list[str] | None = None) -> Verdict:
    """The suite in `worktree`, under `project`'s interpreter (default: the worktree's).

    A ticket worktree is a fresh checkout: the venv the owner's project runs in is
    gitignored and exists only in her checkout, which is why `project` is separate.
    `only` narrows the run to those test ids.
    """
    worktree = Path(worktree)
    python = interpreter(Path(project) if project is not None else worktree)
    if not Path(python).is_file():
        return _error(python, {})
    # `python -m pytest` without pytest exits 1 - the code for "tests failed". Ask first,
    # so a missing tool escalates instead of sending a fixer after it.
    if not _imports(python, "pytest"):
        return _error(f"pytest is not installed for {python}, so the tests cannot run. "
                      f"Install it in that environment.", {})
    thresholds = ruleset.get("thresholds") or {}
    minimum = float(thresholds.get("min_coverage_pct") or 0)
    measure = minimum > 0 and not only and _imports(python, "pytest_cov")
    argv = [python, *ARGS, *(["--cov=.", "--cov-report=term"] if measure else []),
            *(only or [])]

    # No __pycache__ left behind: `taller scan` promises to write nothing.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
           "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("PYTEST_ADDOPTS", None)
    started = time.monotonic()
    try:
        completed = inference._run_bounded(argv, input="", encoding="utf-8", errors="replace",
                                           cwd=str(worktree), timeout=timeout_s, env=env)
    except subprocess.TimeoutExpired:
        return _error(f"The test suite did not finish within {timeout_s:g} s.", {})
    except OSError as exc:
        return _error(f"The test suite could not start: {exc}", {})
    duration = round(time.monotonic() - started, 2)

    output = (completed.stdout or "") + (completed.stderr or "")
    metrics: dict[str, Any] = {**_outcome(output), "duration_s": duration}
    code = completed.returncode

    if code == 5:                                       # no tests collected
        return verdict(GATE, [], {**metrics, "tests_run": 0, "tests_passed": 0})
    if code not in (0, 1):
        return _error(f"pytest exited with code {code}.\n{_tail(output)}", metrics)

    findings: list[Finding] = []
    if code == 1:
        for test_id in dict.fromkeys(_FAILED.findall(output)):
            findings.append(finding(
                "tests.failed", test_id.split("::", 1)[0], 0, f"{test_id} failed.",
                "Fix the code under test. The test itself may not be changed."))
            findings[-1]["test_id"] = test_id
        if not findings:
            # Exit 1 naming no failed test is pytest failing, not a test failing.
            return _error(f"pytest exited with code 1 but named no failed test.\n"
                          f"{_tail(output)}", metrics)

    if measure:
        total = _TOTAL.search(output)
        if total:
            metrics["coverage_pct"] = float(total.group(1))
            if metrics["coverage_pct"] < minimum:
                findings.append(finding(
                    "tests.coverage-below-minimum", "", 0,
                    f"Coverage is {metrics['coverage_pct']:g}%; the project asks for "
                    f"{minimum:g}%.", "Add tests for the code this change introduced."))
    return verdict(GATE, findings, metrics)


scan = run


def failing(worktree: Path | str, ids: list[str], ruleset: Mapping[str, Any], *,
            project: Path | str | None = None) -> set[str]:
    """Which of `ids` also fail in `worktree` (main, for a failure already there)."""
    if not ids:
        return set()
    present = [i for i in ids if (Path(worktree) / i.split("::", 1)[0]).is_file()]
    if not present:
        return set()
    result = run(worktree, ruleset, project=project, only=present)
    if result["result"] == "error":
        return set()
    return {f.get("test_id") for f in result["findings"] if f["rule"] == "tests.failed"}


def interpreter(project: Path) -> str:
    """The project's venv interpreter if it has a venv, else Taller's own.

    Give it the owner's checkout, not a ticket worktree: the venv is gitignored.
    """
    for name in ("venv", ".venv"):
        root = project / name
        if root.is_dir():
            for candidate in (root / "Scripts" / "python.exe", root / "bin" / "python"):
                if candidate.is_file():
                    return str(candidate)
            return (f"The project has a {name}/ directory with no Python interpreter "
                    f"in it, so its tests cannot run.")
    return sys.executable


def _imports(python: str, module: str) -> bool:
    try:
        return subprocess.run([python, "-c", f"import {module}"], capture_output=True,
                              timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _outcome(output: str) -> dict[str, int]:
    tally = {"passed": 0, "failed": 0, "errors": 0}
    summary = [line for line in output.splitlines() if " in " in line and _OUTCOME.search(line)]
    for count, word in _OUTCOME.findall(summary[-1] if summary else ""):
        tally["errors" if word.startswith("error") else word] += int(count)
    return {"tests_run": sum(tally.values()), "tests_passed": tally["passed"]}


def _tail(output: str) -> str:
    return "\n".join(output.strip().splitlines()[-TAIL_LINES:])


def _error(message: str, metrics: dict[str, Any]) -> Verdict:
    return {"gate": GATE, "result": "error", "findings": [], "metrics": metrics,
            "error": message}
