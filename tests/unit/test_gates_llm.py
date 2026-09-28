"""The three model gates - security, quality, ux - and doctor's phase C row.

Spec 9.1, 9.7 (LLM gates declare severity and remediation per finding), 4.5
(every security rule is non-suppressible), 15.4.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

import support
from taller import config, constitution, doctor, overrides
from taller.gates import llm

TICKET = {"id": 7, "title": "Ledger page", "words": "Show the ledger to the team."}
DIFF = "diff --git a/routes/__init__.py b/routes/__init__.py\n+@bp.get('/ledger')\n"
MISSING_PERMISSION = {"rule": "security.missing-permission", "severity": "HIGH",
                      "file": "routes/__init__.py", "line": 16,
                      "message": "The ledger route has no permission check.",
                      "fix_hint": "Add @permission_required('ledger.view').",
                      "remediation": "agent"}


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude) -> Path:
    return support.new_project()


@pytest.fixture
def script(tmp_path: Path, monkeypatch):
    path = tmp_path / "script.json"

    def install(**answers):
        path.write_text(json.dumps(answers), encoding="utf-8")
        monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(path))
    return install


def gate(project: Path, name: str):
    return llm.run(name, project, TICKET, DIFF, constitution.resolve(project),
                   config.load_hub_config())


def test_a_security_finding_comes_back_as_a_finding(project, script, stub_claude):
    script(gate_security=[{"value": {"findings": [MISSING_PERMISSION]}}])

    verdict, result = gate(project, "security")

    assert result.ok and verdict["result"] == "fail"
    assert verdict["findings"] == [{**MISSING_PERMISSION, "gate": "security",
                                    "overridden": None}]
    argv = stub_claude.last()
    assert "--resume" not in argv and "--json-schema" in argv


def test_an_empty_list_is_a_pass(project, script):
    script(gate_quality=[{"value": {"findings": []}}])

    verdict, _ = gate(project, "quality")

    assert (verdict["gate"], verdict["result"], verdict["findings"]) == ("quality", "pass", [])


def test_a_finding_outside_the_gates_domain_is_dropped_with_a_note(project, script):
    stray = {**MISSING_PERMISSION, "rule": "quality.dead-code"}
    shouting = {**MISSING_PERMISSION, "severity": "CRITICAL"}
    script(gate_security=[{"value": {"findings": [stray, MISSING_PERMISSION, shouting,
                                                  "not an object"]}}])

    verdict, _ = gate(project, "security")

    assert [f["rule"] for f in verdict["findings"]] == ["security.missing-permission"]
    dropped = " ".join(verdict["metrics"]["dropped"])
    assert "quality.dead-code" in dropped and "CRITICAL" in dropped
    assert len(verdict["metrics"]["dropped"]) == 3


def test_a_line_that_is_not_a_number_becomes_zero(project, script):
    script(gate_ux=[{"value": {"findings": [{**MISSING_PERMISSION, "rule": "ux.contrast",
                                             "line": None, "remediation": "escalate"}]}}])

    verdict, _ = gate(project, "ux")

    assert verdict["findings"][0]["line"] == 0


def test_an_unusable_answer_twice_is_an_error_verdict(project, script):
    script(gate_quality=[{"value": {"verdict": "fine"}}, {"fail": "the model gave up"}])

    verdict, result = gate(project, "quality")

    assert verdict["result"] == "error" and not result.ok
    assert "quality" in verdict["error"] and verdict["findings"] == []


def test_an_unusable_answer_once_is_retried(project, script):
    script(gate_quality=[{"fail": "overloaded"}, {"value": {"findings": []}}])

    verdict, result = gate(project, "quality")

    assert verdict["result"] == "pass" and result.ok


def test_every_dispatch_is_reported_for_spend(project, script):
    script(gate_quality=[{"fail": "overloaded"}, {"value": {"findings": []}}])
    seen = []

    llm.run("quality", project, TICKET, DIFF, constitution.resolve(project),
            config.load_hub_config(), on_result=seen.append)

    assert [r.ok for r in seen] == [False, True]


def test_the_ux_gate_is_told_the_ui_language(project):
    ruleset = constitution.resolve(project)

    ux = llm.prompt_for("ux", TICKET, DIFF, ruleset)
    security = llm.prompt_for("security", TICKET, DIFF, ruleset)

    assert "UI language: es" in ux and "UI language" not in security
    assert DIFF in ux and "Ledger page" in ux


def test_security_findings_cannot_be_suppressed(project):
    ruleset = {**constitution.resolve(project), "overrides": [
        {"rule": "security.missing-permission", "scope": "*", "reason": "internal only",
         "until": date(2099, 1, 1), "source": "overrides.md"}]}
    found = {**MISSING_PERMISSION, "gate": "security", "overridden": None}

    applied = overrides.apply([found], ruleset)

    assert applied[0]["severity"] == "HIGH" and applied[0]["overridden"] is None
    assert [f["rule"] for f in applied[1:]] == ["constitution.override-not-permitted"]


# --- dry run and doctor's phase C row --------------------------------------------------

def test_a_dry_run_dispatches_nothing(project, stub_claude):
    before = len(stub_claude.calls())

    problems = [llm.dry_run(name, constitution.resolve(project), config.load_hub_config())
                for name in ("security", "quality", "ux")]

    assert problems == [None, None, None] and len(stub_claude.calls()) == before


def test_a_dry_run_reports_a_model_the_probe_found_unreachable(project):
    cfg = config.load_hub_config()
    model = config.resolve_model("gate_security", cfg)
    support.write(Path(cfg_probe_path()), json.dumps(
        {"at": "2026-09-28", "models": {model: {"ok": False, "error": "not on this plan"}}}))

    problem = llm.dry_run("security", constitution.resolve(project), cfg)

    assert problem and model in problem


def cfg_probe_path() -> str:
    from taller import paths
    return str(paths.models_probe())


def test_phase_c_row_passes_on_a_created_project(project):
    checks = doctor.run_checks()

    row = [c for c in checks if c.phase == "C"]
    assert [(c.name, c.status) for c in row] == [
        ("toolshed: every gate executes; smoke configuration valid", doctor.PASS)], row
    assert "C" not in {c.phase for c in checks if c.status == doctor.SKIP}


def test_an_unset_smoke_secret_is_reported(project, monkeypatch):
    monkeypatch.delenv("TALLER_SMOKE_SECRET", raising=False)
    support.write(project / ".taller" / "taller.yml",
                  "smoke:\n  auth:\n    kind: basic\n    user: smoke\n"
                  "    secret: \"$TALLER_SMOKE_SECRET\"\n")

    row = [c for c in doctor.run_checks() if c.phase == "C"][0]

    assert row.status == doctor.FAIL and "TALLER_SMOKE_SECRET" in row.detail


def test_a_smoke_block_without_boot_is_reported(project):
    support.write(project / ".taller" / "taller.yml", "smoke:\n  boot: \"\"\n")

    row = [c for c in doctor.run_checks() if c.phase == "C"][0]

    assert row.status == doctor.FAIL and "boot" in row.detail
