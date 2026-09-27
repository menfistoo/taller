"""`overrides.md`: parse it, decide what it may suppress, downgrade the rest.

Spec 4.5. A gate emits its findings without knowing about any of this; a finding
covered by an active override is **downgraded to `NIT` and annotated with the
reason**, never dropped. An override is a decision to ship a known deviation, not
a decision to stop knowing about it, so it stays visible in the verdict file, on
the cockpit and in `taller scan`.

Pure over its arguments (spec 10.2): nothing here reads the filesystem, the clock
excepted — `until` is compared against today, which is the whole point of it.
"""

from __future__ import annotations

import fnmatch
from datetime import date, datetime
from typing import Any

import yaml

from .errors import ConfigError

Override = dict[str, Any]
Finding = dict[str, Any]

# Rule ids the deterministic gates declare (spec 9.7). Used only to tell the
# owner about a `non_suppressible` entry that names nothing.
DECLARED_RULE_IDS = frozenset({
    "brand.hardcoded-color",
    "brand.hardcoded-font",
    "constitution.layer-violation",
    "constitution.root-markdown",
    "constitution.single-use-script",
    "constitution.commit-message-shape",
    "constitution.new-ui-literal",
    "constitution.resolved-snapshot-stale",
    "constitution.resolved-snapshot-modified",
    "constitution.override-without-reason",
    "constitution.override-expired",
    "constitution.override-not-permitted",
    "constitution.unknown-rule-id",
    "size.file-too-long",
    "size.function-too-long",
    "size.duplicate-block",
    "tests.failed",
    "tests.error",
    "tests.coverage-below-minimum",
    "smoke.boot-failed",
    "smoke.route-error",
    "smoke.not-rendered",
    "smoke.timeout",
    "smoke.unmapped-template",
})

# The three LLM gates declare their rule ids in their own agent definition (spec
# 9.7), so no list here can enumerate them. An id in one of these domains is
# therefore accepted rather than reported as unknown: a false "unknown rule id"
# on every security rule the owner protects would teach them to ignore the rule.
UNENUMERABLE_DOMAINS = frozenset({"security", "quality", "ux"})

# Spec 4.5, clause 1: every rule of the security gate, by domain, so a security
# rule added later is protected without anyone remembering to list it.
NON_SUPPRESSIBLE_DOMAIN = "security"

DEFAULT_SOURCE = ".taller/constitution/overrides.md"


def domain_of(rule: str) -> str:
    """The subject area of a rule id: `<domain>.<rule>` (spec 4.5)."""
    return rule.split(".", 1)[0]


def parse(text: str, source: str = DEFAULT_SOURCE) -> list[Override]:
    """The overrides declared in one `overrides.md`.

    A file with no front matter yields `[]`: a project with no overrides is the
    normal case, not an error. An *unterminated* block is an error, because
    reading it as empty would make a recorded suppression silently disappear.

    `source` rides along on each override so that `Finding.overridden` can name
    where the decision was recorded (spec 7.4). Spec 4.5's `Override` has four
    keys; this is the fifth, and the only one not read from the file.
    """
    front = _front_matter(text)
    raw = front.get("overrides") or []
    if not isinstance(raw, list):
        raise ConfigError(f"{source}: `overrides` must be a list of entries.")

    parsed: list[Override] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ConfigError(f"{source}: every override is a mapping, not {entry!r}.")
        rule = entry.get("rule")
        if not rule:
            raise ConfigError(f"{source}: an override with no `rule` cannot match anything.")
        parsed.append({
            "rule": str(rule),
            "scope": str(entry.get("scope") or "*"),
            "reason": entry.get("reason"),
            "until": _as_date(entry.get("until"), source),
            "source": source,
        })
    return parsed


def is_suppressible(rule: str, ruleset: dict[str, Any]) -> bool:
    """False for every security-gate rule and every id in `non_suppressible`.

    The list is resolved through chain 1 and append-only (spec 4.4), so a project
    can add to the floor and never remove from it.
    """
    if domain_of(rule) == NON_SUPPRESSIBLE_DOMAIN:
        return False
    return rule not in (ruleset.get("non_suppressible") or [])


def apply(findings: list[Finding], ruleset: dict[str, Any]) -> list[Finding]:
    """Downgrade what an active override covers; report what it may not.

    Returns a new list: the given findings (copied, so a caller's list is never
    mutated) followed by the findings this module raises about the overrides
    themselves. Never shorter than what it was given.
    """
    out = [dict(finding) for finding in findings]
    reported: list[Finding] = []
    active: list[Override] = []

    for override in ruleset.get("overrides") or []:
        problems = _problems_with(override, ruleset)
        if problems:
            reported.extend(problems)
            continue           # a malformed or refused override suppresses nothing
        active.append(override)

    for finding in out:
        for override in active:
            if override["rule"] != finding.get("rule"):
                continue
            if not _scope_matches(override["scope"], finding.get("file") or ""):
                continue
            finding["severity"] = "NIT"
            finding["overridden"] = {"reason": override["reason"],
                                     "source": override["source"]}
            break

    reported.extend(_unknown_ids(ruleset))
    return out + reported


# --- internals ---------------------------------------------------------------

def _problems_with(override: Override, ruleset: dict[str, Any]) -> list[Finding]:
    """Each condition gets its own rule id: spec 15.1 asserts by id."""
    problems: list[Finding] = []
    source = override.get("source") or DEFAULT_SOURCE
    rule = override["rule"]

    if not str(override.get("reason") or "").strip():
        problems.append(_finding(
            "constitution.override-without-reason", "HIGH", source,
            f"The override of {rule} records no reason, so it suppresses nothing.",
            "Add a `reason:` naming the decision, or delete the override.",
        ))

    until = override.get("until")
    if isinstance(until, date) and until < date.today():
        problems.append(_finding(
            "constitution.override-expired", "HIGH", source,
            f"The override of {rule} expired on {until.isoformat()}.",
            "Extend `until:` with a fresh reason, or remove the override and fix the finding.",
        ))

    if not is_suppressible(rule, ruleset):
        problems.append(_finding(
            "constitution.override-not-permitted", "BLOCKER", source,
            f"{rule} may not be suppressed by an override.",
            "Every security-gate rule and every id in `non_suppressible` is protected (spec 4.5).",
        ))

    return problems


def _unknown_ids(ruleset: dict[str, Any]) -> list[Finding]:
    """`non_suppressible` entries no gate declares (spec 4.5).

    An entry naming nothing protects nothing while looking as if it does. Only
    the deterministic domains are checked; see `UNENUMERABLE_DOMAINS`.
    """
    out: list[Finding] = []
    for rule in ruleset.get("non_suppressible") or []:
        if rule in DECLARED_RULE_IDS or domain_of(rule) in UNENUMERABLE_DOMAINS:
            continue
        out.append(_finding(
            "constitution.unknown-rule-id", "MEDIUM", "taller.yml",
            f"`non_suppressible` names {rule}, which no gate declares.",
            "Check the id against spec 9.7; a typo here protects nothing.",
        ))
    return out


def _finding(rule: str, severity: str, file: str, message: str,
             fix_hint: str | None) -> Finding:
    return {
        "gate": "constitution",
        "severity": severity,
        "rule": rule,
        "file": file,
        "line": 0,
        "message": message,
        "fix_hint": fix_hint,
        "overridden": None,
    }


def _scope_matches(scope: str, file: str) -> bool:
    """Glob match, or `*` for project-wide.

    Known limitation, recorded rather than fixed: `fnmatch` has no recursive
    globbing, so `**` behaves as `*` and `*` matches a path separator. For scope
    matching that is slightly permissive in the safe direction — an override
    covers a little more than its author wrote — and it is worth knowing before
    someone "corrects" it into `pathlib.PurePath.match`, which would silently
    stop matching the `legacy/**` scopes people actually write.
    """
    if scope == "*":
        return True
    return fnmatch.fnmatch(file.replace("\\", "/"), scope)


def _front_matter(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() in {"---", "..."}:
            block = "\n".join(lines[1:index])
            break
    else:
        raise ConfigError(
            "overrides.md opens a front matter block that is never closed by `---`."
        )
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise ConfigError(f"overrides.md front matter is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError("overrides.md front matter must be a mapping.")
    return data


def _as_date(value: Any, source: str) -> date | None:
    """`until` as a date. YAML gives one for `2026-12-31`; a snapshot gives a str."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ConfigError(
            f"{source}: `until: {value}` is not a date in YYYY-MM-DD form."
        ) from exc
