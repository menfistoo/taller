"""What GitHub says, and the rule for her to turn on. Taller changes nothing there.

Spec 13 (branch protection: require a pull request and a green `taller-ci`) and
15.4's F row (the latest `taller-ci` run on main that was a real change is
green). The owner's decision, 2026-09-29: Taller prints the rule and reports
when it is off; it never edits a setting on her account.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import support
from taller import discovery, doctor, github, paths
from taller.prompter import ScriptedPrompter

REPO = "someone/toolshed"


def gh(payloads: dict[str, Any_], seen: list[list[str]] | None = None):
    """A fake `gh`: the first key whose words all appear in the argv answers."""
    def fake(args: list[str], input: str | None = None):
        if seen is not None:
            seen.append(args)
        for key, payload in payloads.items():
            if all(word in " ".join(args) for word in key.split()):
                if payload is None:
                    return None
                return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        return subprocess.CompletedProcess(args, 1, "", "not found")
    return fake


Any_ = object  # a payload is whatever json.dumps accepts


def runs(*entries: tuple[str, str]) -> list[dict]:
    return [{"conclusion": conclusion, "status": "completed", "headSha": sha,
             "createdAt": f"2026-09-2{n}T10:00:00Z"}
            for n, (sha, conclusion) in enumerate(entries)]


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    project = support.new_project()
    monkeypatch.setattr("taller.issues.repo_of", lambda path: REPO)
    return project


def a_real_change(project: Path) -> str:
    support.write(project / "static" / "css" / "app.css", "h1 { color: inherit; }\n")
    support.git(project, "add", "--all")
    support.git(project, "commit", "-q", "-m", "fix(ui): the heading")
    return support.git(project, "rev-parse", "HEAD").strip()


def a_ticket_file_change(project: Path) -> str:
    support.write(project / ".taller" / "work" / "0001-x" / "notes.md", "a note\n")
    support.git(project, "add", "--all")
    support.git(project, "commit", "-q", "-m", "docs(ticket): a note")
    return support.git(project, "rev-parse", "HEAD").strip()


# --- the latest run that was a real change ------------------------------------------

def test_a_green_full_run_passes(project, monkeypatch):
    sha = a_real_change(project)
    monkeypatch.setattr(discovery, "_run_gh", gh({"run list": runs((sha, "success"))}))

    assert github.latest_ci(project, REPO)["state"] == "green"


def test_a_green_ticket_files_run_does_not_count(project, monkeypatch):
    real = a_real_change(project)
    tickets_only = a_ticket_file_change(project)
    monkeypatch.setattr(discovery, "_run_gh", gh({
        "run list": runs((real, "failure"), (tickets_only, "success"))}))

    found = github.latest_ci(project, REPO)

    assert found["state"] == "failed"          # the ticket-file run is skipped
    assert real[:7] in found["detail"]


def test_a_run_on_a_commit_this_checkout_does_not_have_is_unknown(project, monkeypatch):
    monkeypatch.setattr(discovery, "_run_gh", gh({"run list": runs(("0" * 40, "success"))}))

    assert github.latest_ci(project, REPO)["state"] == "unknown"


def test_no_run_at_all_is_reported_as_none(project, monkeypatch):
    monkeypatch.setattr(discovery, "_run_gh", gh({"run list": []}))

    assert github.latest_ci(project, REPO)["state"] == "none"


def test_gh_missing_is_unknown_not_a_failure(project, monkeypatch):
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)

    found = github.latest_ci(project, REPO)

    assert found["state"] == "unknown" and "gh" in found["detail"]


# --- branch protection ----------------------------------------------------------------

PROTECTED = [{"id": 5, "name": "main", "target": "branch"}]
RULES = {"conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
         "rules": [{"type": "pull_request"},
                   {"type": "required_status_checks",
                    "parameters": {"required_status_checks": [{"context": "taller-ci"}]}}]}


def test_a_ruleset_requiring_both_passes(project, monkeypatch):
    monkeypatch.setattr(discovery, "_run_gh",
                        gh({"rulesets/5": RULES, "rulesets": PROTECTED}))

    assert github.protection(REPO)["ok"] is True


def test_protection_missing_is_reported_with_what_to_turn_on(project, monkeypatch):
    monkeypatch.setattr(discovery, "_run_gh", gh({"rulesets": []}))

    found = github.protection(REPO)

    assert found["ok"] is False
    assert "pull request" in found["detail"]
    assert "taller-ci" in github.ruleset_instructions(REPO)


def test_a_ruleset_without_the_check_is_not_enough(project, monkeypatch):
    only_pr = {**RULES, "rules": [{"type": "pull_request"}]}
    monkeypatch.setattr(discovery, "_run_gh",
                        gh({"rulesets/5": only_pr, "rulesets": PROTECTED}))

    assert github.protection(REPO)["ok"] is False


def test_protect_prints_and_changes_nothing(project, monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr(discovery, "_run_gh", gh({"rulesets": []}, seen))
    prompter = ScriptedPrompter({})

    from taller import cli

    assert cli.main(["github", "protect", "--path", str(project)], prompter) == 0

    said = "\n".join(prompter.said)
    assert "taller-ci" in said and "will not change" in said.lower()
    assert not [args for args in seen
                if any(word in args for word in ("--method", "POST", "PUT", "PATCH", "DELETE"))]


# --- doctor's F rows --------------------------------------------------------------------

def test_doctor_reports_both(project, monkeypatch):
    sha = a_real_change(project)
    monkeypatch.setattr(discovery, "_run_gh", gh({
        "run list": runs((sha, "success")), "rulesets/5": RULES, "rulesets": PROTECTED}))

    support.write(paths.hub_config(), "ci:\n  taller_source: taller @ git+file:///t\n")

    rows = [c for c in doctor.run_checks() if c.phase == "F"]

    assert len(rows) == 3 and {c.status for c in rows} == {doctor.PASS}


def test_doctor_skips_both_without_a_remote(tmp_home, identity, stub_claude, monkeypatch):
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    support.new_project()

    rows = [c for c in doctor.run_checks() if c.phase == "F"]

    assert len(rows) == 3 and {c.status for c in rows} == {doctor.SKIP}
    assert all("no GitHub remote" in c.detail for c in rows)
