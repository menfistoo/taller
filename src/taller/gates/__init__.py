"""Gates: the rule table, which gates run, where a finding goes, and the verdict file.

Spec 9. Severity belongs to the rule id, not to whoever reports it (9.7), because
three mechanisms key off it - the fixer, the owner's summary, and the override
downgrade (4.5). `remediation` decides who acts on a BLOCKER or HIGH: `agent`
sends the fixer, `command` runs something deterministic, `escalate` asks the
owner. A gate is never argued with at review time (9.8).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

import yaml

from .. import globs

Finding = dict[str, Any]
Verdict = dict[str, Any]

SEVERITIES = ("BLOCKER", "HIGH", "MEDIUM", "LOW", "NIT")
ACTED_ON = ("BLOCKER", "HIGH")
REMEDIATIONS = ("agent", "command", "escalate")

# §9.7, verbatim: rule -> (severity, remediation). None is "owner summary only"
# for a MEDIUM, or "logged" for a LOW.
RULES: dict[str, tuple[str, str | None]] = {
    "brand.hardcoded-color": ("HIGH", "agent"),
    "brand.hardcoded-font": ("HIGH", "agent"),
    "constitution.layer-violation": ("HIGH", "agent"),
    "constitution.root-markdown": ("MEDIUM", "agent"),
    "constitution.single-use-script": ("MEDIUM", "agent"),
    "constitution.commit-message-shape": ("MEDIUM", "agent"),
    "constitution.new-ui-literal": ("MEDIUM", None),
    "constitution.resolved-snapshot-stale": ("HIGH", "command"),
    "constitution.resolved-snapshot-modified": ("BLOCKER", "escalate"),
    "constitution.override-without-reason": ("HIGH", "escalate"),
    "constitution.override-expired": ("HIGH", "escalate"),
    "constitution.override-not-permitted": ("BLOCKER", "escalate"),
    "constitution.unknown-rule-id": ("MEDIUM", "escalate"),
    "size.file-too-long": ("MEDIUM", "escalate"),
    "size.function-too-long": ("MEDIUM", "agent"),
    "size.duplicate-block": ("LOW", None),
    "tests.failed": ("BLOCKER", "agent"),
    "tests.error": ("BLOCKER", "escalate"),
    # §9.7's closing paragraph: only fires when a project sets a minimum.
    "tests.coverage-below-minimum": ("MEDIUM", "escalate"),
    "smoke.boot-failed": ("BLOCKER", "escalate"),
    "smoke.route-error": ("BLOCKER", "agent"),
    "smoke.not-rendered": ("HIGH", "escalate"),
    "smoke.timeout": ("HIGH", "escalate"),
    "smoke.unmapped-template": ("MEDIUM", None),
}

# The gate a rule belongs to, by its domain.
_GATE_OF_DOMAIN = {"brand": "constitution", "constitution": "constitution", "size": "size",
                   "tests": "tests", "smoke": "smoke"}

# §9.2, in the order gates are reported.
ORDER = ("constitution", "size", "tests", "security", "quality", "ux")
MODEL_FREE = ("constitution", "size", "tests")
LLM_GATES = ("security", "quality", "ux")


def finding(rule: str, file: str = "", line: int = 0, message: str = "",
            fix_hint: str | None = None, *, gate: str | None = None) -> Finding:
    """A Finding for a table rule, its severity taken from §9.7."""
    severity = RULES[rule][0]
    return {"gate": gate or _GATE_OF_DOMAIN[rule.split(".", 1)[0]], "severity": severity,
            "rule": rule, "file": file, "line": int(line), "message": message,
            "fix_hint": fix_hint, "overridden": None}


def select(ticket: Mapping[str, Any], diff: Mapping[str, Any], ruleset: Mapping[str, Any],
           *, has_tests: bool = False) -> list[str]:
    """The gates §9.2 runs at ⑤ for this change. Smoke is ⑥'s, never selected here."""
    paths = [f["path"] for f in diff.get("files") or []]
    rules = ruleset.get("paths") or {}
    full = ticket.get("lane") == "full"

    def any_match(key: str) -> bool:
        return any(globs.any_match(path, list(rules.get(key) or [])) for path in paths)

    chosen = {"constitution", "size"}
    if has_tests or any(path.endswith(".py") for path in paths):
        chosen.add("tests")
    if any_match("security_sensitive"):
        chosen.add("security")
    if full:
        chosen.add("quality")
        if any_match("ui"):
            chosen.add("ux")
    return [gate for gate in ORDER if gate in chosen]


def route(findings: list[Finding]) -> dict[str, list[Finding]]:
    """Where each finding goes (§9.3): agent, command, escalate, summary, or log."""
    out: dict[str, list[Finding]] = {"agent": [], "command": [], "escalate": [],
                                     "summary": [], "log": []}
    for found in findings:
        severity = found.get("severity")
        if found.get("overridden") or severity in ("LOW", "NIT"):
            out["log"].append(found)
        elif severity == "MEDIUM":
            out["summary"].append(found)
        else:
            remediation = found.get("remediation") or RULES.get(found.get("rule"), (None, None))[1]
            # A BLOCKER or HIGH with no stated remediation is the owner's call.
            out[remediation if remediation in REMEDIATIONS else "escalate"].append(found)
    return out


def errors(verdicts: list[Verdict]) -> list[Finding]:
    """A gate that could not run is a BLOCKER for the owner, never a pass (7.4)."""
    return [{"gate": v["gate"], "severity": "BLOCKER", "rule": f"{v['gate']}.error",
             "file": "", "line": 0,
             "message": f"The {v['gate']} gate could not run: {v.get('error') or 'no detail'}",
             "fix_hint": None, "overridden": None, "remediation": "escalate"}
            for v in verdicts if v.get("result") == "error"]


def counts(findings: list[Finding]) -> dict[str, int]:
    tally = {severity.lower(): 0 for severity in SEVERITIES}
    for found in findings:
        key = str(found.get("severity", "")).lower()
        if key in tally:
            tally[key] += 1
    return tally


def render_verdict(verdict: Verdict, *, hub_sha: str, prose: str) -> bytes:
    """`gates/<name>.md`: YAML front matter, then prose for the owner (7.4)."""
    front = {
        "gate": verdict["gate"],
        "result": verdict["result"],
        "hub_sha": hub_sha,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "counts": counts(verdict.get("findings") or []),
        "metrics": verdict.get("metrics") or {},
        "findings": verdict.get("findings") or [],
    }
    head = yaml.safe_dump(front, allow_unicode=True, sort_keys=False)
    return f"---\n{head}---\n\n{prose.strip()}\n".encode("utf-8")


def parse_verdict(text: str) -> Verdict:
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError("a verdict file starts with front matter")
    end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    data = yaml.safe_load("\n".join(lines[1:end])) or {}
    data["prose"] = "\n".join(lines[end + 1:]).strip()
    return data
