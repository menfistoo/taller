"""`taller scan [path] [--all]`: every model-free gate over the whole tree.

Spec 9.5: the same rules a change is held to, applied to what is already there -
the figures behind Health (spec 12, criterion 15). Smoke is exempt: it needs a
change to exercise. Nothing is written: no commit, no file, no ticket.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .. import constitution, gates, registry, tickets
from ..errors import TallerError
from ..gates import constitution as constitution_gate
from ..gates import diff as gate_diff
from ..gates import size as size_gate
from ..gates import tests as tests_gate
from ..prompter import Prompter
from .common import project_path

TOP_RULES = 5
SNAPSHOT = ".taller/resolved.json"


def health(project: Path, ruleset: Mapping[str, Any]) -> dict[str, Any]:
    """Counts by severity, the most frequent rules, and the tests' figures."""
    tree = gate_diff.tree(project)
    verdicts = [
        constitution_gate.scan(tree, ruleset, snapshot_sha=_snapshot_sha(project)),
        size_gate.scan(tree, ruleset),
        tests_gate.scan(project, ruleset),
    ]
    findings = [f for v in verdicts for f in v["findings"]]
    tally = Counter(f["rule"] for f in findings)
    tests_metrics = next(v["metrics"] for v in verdicts if v["gate"] == "tests")
    return {
        "gates": [v["gate"] for v in verdicts],
        "counts": gates.counts(findings),
        "top_rules": sorted(tally.items(), key=lambda item: (-item[1], item[0]))[:TOP_RULES],
        "tests": tests_metrics,
        "errors": [f"{v['gate']}: {v.get('error', '')}" for v in verdicts
                   if v["result"] == "error"],
    }


def render(name: str, figures: Mapping[str, Any]) -> str:
    counts = figures["counts"]
    lines = [name, "  findings: " + ", ".join(f"{counts[k]} {k}" for k in
                                              ("blocker", "high", "medium", "low", "nit"))]
    if figures["top_rules"]:
        lines.append("  top rules: " + ", ".join(f"{rule} ×{count}"
                                                 for rule, count in figures["top_rules"]))
    t = figures["tests"]
    if "tests_run" in t:
        line = f"  tests: {t['tests_run']} run, {t.get('tests_passed', 0)} passed"
        if "coverage_pct" in t:
            line += f", {t['coverage_pct']:g}% covered"
        if "duration_s" in t:
            line += f", {t['duration_s']:g} s"
        lines.append(line)
    else:
        lines.append("  tests: could not run")
    lines.extend(f"  could not run - {error}" for error in figures["errors"])
    return "\n".join(lines)


def run(args: Any, prompter: Prompter) -> int:
    if getattr(args, "all", False):
        entries = [e for e in registry.list_projects() if registry.is_adopted(e)]
        if not entries:
            prompter.say("No adopted projects to scan.")
            return 0
    else:
        entries = [registry.get_project(project_path(getattr(args, "path", None)))]
    for entry in entries:
        project = Path(entry["path"])
        try:
            figures = health(project, constitution.resolve(project))
        except TallerError as exc:
            prompter.say(f"{entry['name']}\n  could not scan: {exc}")
            continue
        prompter.say(render(entry["name"], figures))
    return 0


def _snapshot_sha(project: Path) -> str | None:
    try:
        raw = tickets.read_main(project, SNAPSHOT)
        return json.loads(raw.decode("utf-8")).get("hub_sha") if raw else None
    except (ValueError, AttributeError, TallerError, OSError):
        return None
