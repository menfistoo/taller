"""Spec 4.5 — what an override may suppress, and what happens when it may not.

`overrides.apply` is pure over its arguments (spec 10.2), so every case here is a
literal `RuleSet` fragment and a list of findings. No hub, no project, no disk.

The invariant numbers are the plan's, task 12.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from taller import overrides
from taller.errors import ConfigError

TODAY = date.today()


def ruleset(*, over: list[dict] | None = None,
            non_suppressible: list[str] | None = None) -> dict:
    """The two `RuleSet` keys this module reads, and nothing else."""
    return {
        "overrides": over if over is not None else [],
        "non_suppressible": non_suppressible if non_suppressible is not None else [],
    }


def finding(rule: str, *, file: str = "routes/report.py",
            severity: str = "MEDIUM", gate: str = "size") -> dict:
    return {
        "gate": gate,
        "severity": severity,
        "rule": rule,
        "file": file,
        "line": 12,
        "message": "It is what it is.",
        "fix_hint": None,
        "overridden": None,
    }


def override(rule: str, **kwargs) -> dict:
    data = {"rule": rule, "scope": "*", "reason": "Recorded decision.",
            "until": None, "source": ".taller/constitution/overrides.md"}
    data.update(kwargs)
    return data


def rules_of(findings: list[dict]) -> list[str]:
    return [f["rule"] for f in findings]


# --- invariant 6: a project with no overrides is the normal case --------------

def test_a_file_with_no_front_matter_parses_to_nothing():
    text = "Prose about why this project overrides nothing at all.\n"
    assert overrides.parse(text) == []


def test_an_empty_file_parses_to_nothing():
    assert overrides.parse("") == []


def test_an_unterminated_front_matter_block_is_an_error():
    """Silently reading it as empty would make a real suppression disappear, and
    the owner would never learn their reason was not recorded."""
    with pytest.raises(ConfigError, match="never closed"):
        overrides.parse("---\noverrides:\n  - rule: size.file-too-long\n")


def test_parse_reads_rule_scope_reason_and_until():
    text = (
        "---\n"
        "overrides:\n"
        "  - rule:   size.file-too-long\n"
        '    scope:  "routes/legacy_report.py"\n'
        '    reason: "Being split ticket by ticket; see 0031."\n'
        "    until:  2026-12-31\n"
        "---\n"
        "\n"
        "Prose context for a human reader.\n"
    )
    parsed = overrides.parse(text, source=".taller/constitution/overrides.md")
    assert len(parsed) == 1
    assert parsed[0] == {
        "rule": "size.file-too-long",
        "scope": "routes/legacy_report.py",
        "reason": "Being split ticket by ticket; see 0031.",
        "until": date(2026, 12, 31),
        # Not in spec 4.5's four keys, but Finding.overridden carries a `source`
        # (spec 7.4) and this is the only place that knows it.
        "source": ".taller/constitution/overrides.md",
    }


# --- invariant 7: scope ------------------------------------------------------

def test_scope_defaults_to_project_wide():
    parsed = overrides.parse(
        "---\noverrides:\n  - rule: size.file-too-long\n    reason: Recorded.\n---\n"
    )
    assert parsed[0]["scope"] == "*"
    assert parsed[0]["until"] is None


def test_a_scope_that_does_not_match_the_file_does_not_suppress():
    result = overrides.apply(
        [finding("size.file-too-long", file="routes/live_report.py")],
        ruleset(over=[override("size.file-too-long", scope="routes/legacy_report.py")]),
    )
    assert result[0]["severity"] == "MEDIUM"
    assert result[0]["overridden"] is None


def test_a_scope_glob_matches_by_path():
    result = overrides.apply(
        [finding("size.file-too-long", file="legacy/reports/annual.py")],
        ruleset(over=[override("size.file-too-long", scope="legacy/**")]),
    )
    assert result[0]["severity"] == "NIT"


# --- invariant 1: downgraded, never removed ---------------------------------

def test_a_matching_override_downgrades_to_nit_and_keeps_the_reason():
    """An override is a decision to ship a known deviation, not to stop knowing
    about it: it stays in the verdict, on the cockpit and in `taller scan`."""
    findings = [finding("size.file-too-long"), finding("size.function-too-long")]
    result = overrides.apply(
        findings,
        ruleset(over=[override("size.file-too-long", reason="Split ticket by ticket.")]),
    )
    assert len(result) == 2, "nothing is removed, ever"
    downgraded = [f for f in result if f["rule"] == "size.file-too-long"][0]
    assert downgraded["severity"] == "NIT"
    assert downgraded["overridden"] == {
        "reason": "Split ticket by ticket.",
        "source": ".taller/constitution/overrides.md",
    }
    untouched = [f for f in result if f["rule"] == "size.function-too-long"][0]
    assert untouched["severity"] == "MEDIUM"
    assert untouched["overridden"] is None


def test_apply_does_not_mutate_the_findings_it_was_given():
    """A gate keeps its own list; the verdict writer takes the returned one."""
    original = finding("size.file-too-long")
    overrides.apply([original], ruleset(over=[override("size.file-too-long")]))
    assert original["severity"] == "MEDIUM"
    assert original["overridden"] is None


def test_findings_come_back_untouched_when_there_are_no_overrides():
    result = overrides.apply([finding("size.file-too-long")], ruleset())
    assert result == [finding("size.file-too-long")]


# --- invariant 5: distinct ids for distinct conditions -----------------------

def test_an_override_without_a_reason_suppresses_nothing_and_is_reported():
    result = overrides.apply(
        [finding("size.file-too-long")],
        ruleset(over=[override("size.file-too-long", reason=None)]),
    )
    assert rules_of(result) == ["size.file-too-long",
                               "constitution.override-without-reason"]
    assert result[0]["severity"] == "MEDIUM", "it suppressed nothing"
    assert result[1]["severity"] == "HIGH"
    assert result[1]["gate"] == "constitution"


def test_an_expired_override_has_its_own_rule_id():
    """Spec 15.1 asserts by id, so two conditions sharing one id could not be
    told apart."""
    result = overrides.apply(
        [finding("size.file-too-long")],
        ruleset(over=[override("size.file-too-long",
                               until=TODAY - timedelta(days=1))]),
    )
    assert rules_of(result) == ["size.file-too-long",
                               "constitution.override-expired"]
    assert result[0]["severity"] == "MEDIUM"
    assert result[1]["severity"] == "HIGH"


def test_an_override_expiring_today_is_still_active():
    """`until` is the last day it applies, not the first day it does not."""
    result = overrides.apply(
        [finding("size.file-too-long")],
        ruleset(over=[override("size.file-too-long", until=TODAY)]),
    )
    assert rules_of(result) == ["size.file-too-long"]
    assert result[0]["severity"] == "NIT"


# --- invariants 2, 3, 4: what may not be suppressed -------------------------

def test_every_security_rule_is_non_suppressible_by_domain():
    """By domain, so a security rule added later is protected without anyone
    remembering to list it (spec 4.5)."""
    result = overrides.apply(
        [finding("security.sql-injection", gate="security", severity="BLOCKER")],
        ruleset(over=[override("security.sql-injection")]),
    )
    assert result[0]["severity"] == "BLOCKER", "not downgraded"
    assert result[0]["overridden"] is None
    assert "constitution.override-not-permitted" in rules_of(result)


def test_a_rule_id_in_non_suppressible_cannot_be_suppressed():
    result = overrides.apply(
        [finding("brand.hardcoded-color", severity="HIGH", gate="constitution")],
        ruleset(over=[override("brand.hardcoded-color")],
                non_suppressible=["brand.hardcoded-color"]),
    )
    assert result[0]["severity"] == "HIGH"
    assert result[0]["overridden"] is None


def test_a_refused_override_is_reported_at_blocker():
    result = overrides.apply(
        [],
        ruleset(over=[override("brand.hardcoded-color")],
                non_suppressible=["brand.hardcoded-color"]),
    )
    assert rules_of(result) == ["constitution.override-not-permitted"]
    assert result[0]["severity"] == "BLOCKER"
    assert result[0]["file"] == ".taller/constitution/overrides.md"


def test_a_non_suppressible_id_no_gate_declares_is_reported():
    """A typo in the list names a rule nothing can report, so it protects
    nothing while looking as if it does (spec 4.5).

    The three LLM gates declare their own ids in their agent definition (spec
    9.7), so their domains cannot be enumerated here and are accepted — asserted
    in the same case, because it is the same predicate deciding both.
    """
    result = overrides.apply([], ruleset(non_suppressible=["size.file-too-lung"]))
    assert rules_of(result) == ["constitution.unknown-rule-id"]
    assert result[0]["severity"] == "MEDIUM"
    assert "size.file-too-lung" in result[0]["message"]

    accepted = overrides.apply(
        [], ruleset(non_suppressible=["security.missing-csrf", "ux.contrast-too-low"])
    )
    assert accepted == []
