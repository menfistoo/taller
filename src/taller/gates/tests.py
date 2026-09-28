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
        timeout_s: float = TIMEOUT_S) -> Verdict:
    worktree = Path(worktree)
    python = interpreter(worktree)
    if isinstance(python, str) and not Path(python).is_file():
        return _error(python, {})
    thresholds = ruleset.get("thresholds") or {}
    minimum = float(thresholds.get("min_coverage_pct") or 0)
    measure = minimum > 0 and _has_pytest_cov(python)
    argv = [python, *ARGS, *(["--cov=.", "--cov-report=term"] if measure else [])]

    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
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
        if not findings:
            findings.append(finding("tests.failed", "", 0,
                                    f"The suite failed.\n{_tail(output)}", None))

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


def interpreter(worktree: Path) -> str:
    """The project's venv interpreter if it has a venv, else Taller's own."""
    for name in ("venv", ".venv"):
        root = worktree / name
        if root.is_dir():
            for candidate in (root / "Scripts" / "python.exe", root / "bin" / "python"):
                if candidate.is_file():
                    return str(candidate)
            return (f"The project has a {name}/ directory with no Python interpreter "
                    f"in it, so its tests cannot run.")
    return sys.executable


def _has_pytest_cov(python: str) -> bool:
    try:
        return subprocess.run([python, "-c", "import pytest_cov"], capture_output=True,
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
