"""doctor.py — every phase A check of spec 15.4, and each one's failure."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

import support
from taller import cli, doctor, hub, paths, scaffold
from taller.prompter import ScriptedPrompter

ANSWERS = {
    "what_it_does": "Tracks which neighbour has borrowed which shared tool.",
    "what_it_is_not": "A marketplace.", "must_never_break": "Who has which tool.",
    "users": "team", "reach": "a private network", "phone": True,
    "stores": "Tools and loans.", "sensitive_data": False, "deploy": "local",
    "first_version": ["Record a loan"],
}


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude) -> Path:
    support.write(paths.hub_config(), yaml.safe_dump(
        {"language": {"code": "en", "ui": "es", "commits": "en"}}))
    hub.commit("setup")
    support.make_brand("harbour")
    hub.commit("brand")
    target = paths.home() / "projects" / "toolshed"
    scaffold.create_project(target, name="toolshed", profile="flask-sqlite",
                            brand="harbour", answers=ANSWERS)
    return target


def by_name(checks, fragment: str) -> doctor.Check:
    matches = [check for check in checks if fragment in check.name]
    assert len(matches) == 1, [check.name for check in checks]
    return matches[0]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          check=True).stdout


def test_a_fresh_project_passes_every_phase_a_check(project: Path):
    checks = doctor.run_checks()

    failed = [(c.name, c.detail) for c in checks if c.status == doctor.FAIL]
    assert failed == []
    skipped_a = [c.name for c in checks if c.status == doctor.SKIP and c.phase == "A"]
    assert skipped_a == [], "a phase A check was skipped"
    assert {c.phase for c in checks if c.status == doctor.SKIP} == {"B", "C", "F"}


def test_the_dispatch_runs_without_an_api_key_and_is_cached(project: Path, stub_claude,
                                                            monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-must-not-reach-the-cli")
    monkeypatch.setenv("STUB_CLAUDE_REFUSE_API_KEY", "1")

    first = by_name(doctor.run_checks(live=True), "subscription")
    dispatches = [argv for argv in stub_claude.calls() if "-p" in argv]
    second = by_name(doctor.run_checks(), "subscription")

    assert first.status == doctor.PASS, first.detail
    assert second.status == doctor.PASS and "passed" in second.detail
    assert [argv for argv in stub_claude.calls() if "-p" in argv] == dispatches, (
        "the cached check dispatched again"
    )


@pytest.mark.parametrize("env, phrase", [
    ({"STUB_CLAUDE_HIDE_FLAGS": "--agents"}, "--agents"),
    ({"STUB_CLAUDE_VERSION": "2.0.1 (Claude Code)"}, "2.0.1"),
])
def test_an_unfit_cli_fails(project: Path, monkeypatch, env, phrase):
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    check = by_name(doctor.run_checks(), "claude CLI")

    assert check.status == doctor.FAIL and phrase in check.detail


def test_a_snapshot_edited_on_main_is_modified_but_a_working_tree_edit_is_not(project: Path):
    snapshot = project / ".taller" / "resolved.json"
    snapshot.write_text(snapshot.read_text(encoding="utf-8").replace('"max_file_lines": 800',
                                                                    '"max_file_lines": 9000'),
                        encoding="utf-8", newline="")
    assert by_name(doctor.run_checks(), "resolved.json").status == doctor.PASS

    git(project, "commit", "--quiet", "-am", "raise my own limits")
    check = by_name(doctor.run_checks(), "resolved.json")
    assert check.status == doctor.FAIL and "modified" in check.detail


def test_a_hub_change_makes_it_stale_and_resolve_fixes_it(project: Path):
    hub.update_config({"thresholds": {"max_file_lines": 400}})
    hub.commit("tighten")

    check = by_name(doctor.run_checks(), "resolved.json")
    assert check.status == doctor.FAIL and "stale" in check.detail
    assert "taller resolve" in check.fix

    assert cli.main(["resolve", str(project)], ScriptedPrompter({})) == 0
    assert by_name(doctor.run_checks(), "resolved.json").status == doctor.PASS


def test_a_missing_merge_driver_fails_with_the_fix(project: Path):
    git(project, "config", "--unset", "merge.ours.driver")

    check = by_name(doctor.run_checks(), "merge.ours")

    assert check.status == doctor.FAIL and "merge.ours.driver true" in check.fix


def test_a_branch_carrying_its_own_snapshot_fails(project: Path):
    git(project, "checkout", "--quiet", "-b", "ticket/0001")
    (project / ".taller" / "resolved.json").write_text("{}\n", encoding="utf-8")
    git(project, "commit", "--quiet", "-am", "my own rules")
    git(project, "checkout", "--quiet", "main")

    check = by_name(doctor.run_checks(), "no branch carries")

    assert check.status == doctor.FAIL and "ticket/0001" in check.detail


def test_a_lock_left_by_a_dead_process_is_reported_not_removed(project: Path):
    lock = paths.project_lock("toolshed")
    support.write(lock, "999999\n")

    check = by_name(doctor.run_checks(), "dead process")

    assert check.status == doctor.FAIL and lock.exists()


def test_no_brand_skips_the_token_check_with_its_reason(tmp_home: Path, identity, stub_claude):
    support.write(paths.hub_config(), yaml.safe_dump(
        {"language": {"code": "en", "ui": "none", "commits": "en"}}))
    scaffold.create_project(paths.home() / "projects" / "cli-tool", name="cli-tool",
                            profile="python-packaged", brand=None, answers=ANSWERS)

    check = by_name(doctor.run_checks(), "brand tokens")

    assert check.status == doctor.SKIP and "none" in check.detail


def test_doctor_writes_nothing_once_its_dispatch_is_cached(project: Path):
    doctor.run_checks()                                  # fills the cache
    before = support.tree_mtimes(paths.home())

    doctor.run_checks()

    assert support.tree_mtimes(paths.home()) == before


def test_the_command_exits_one_on_a_failure(project: Path):
    prompter = ScriptedPrompter({})
    assert cli.main(["doctor"], prompter) == 0
    assert "All checks pass." in prompter.said[-1]

    subprocess.run(["git", "-C", str(project), "config", "--unset", "merge.ours.driver"],
                   check=True)
    assert cli.main(["doctor"], prompter) == 1


def test_a_dispatch_that_never_answers_fails_in_bounded_time(project: Path, monkeypatch):
    """Found in first real use: doctor sat for minutes on a dispatch that never
    answered, because the timeout was the half hour real work gets."""
    import time

    monkeypatch.setattr(doctor, "DISPATCH_CHECK_TIMEOUT", 3.0)
    monkeypatch.setenv("STUB_CLAUDE_HANG", "60")
    started = time.monotonic()

    check = by_name(doctor.run_checks(live=True), "subscription")

    assert check.status == doctor.FAIL and "abandoned" in check.detail
    assert time.monotonic() - started < 30, "the hung process tree was not ended"
    assert "claude update" in check.fix


# --- phase D: tickets --------------------------------------------------------

def test_tickets_that_read_and_are_pushed_pass(project: Path):
    from taller import tickets

    tickets.create(project, title="First", words="w", kind="idea")

    check = by_name(doctor.run_checks(), "tickets readable")
    assert check.status == doctor.PASS and check.phase == "D"


def test_a_broken_status_yml_fails_the_ticket_check_and_names_it(project: Path):
    from taller import gitio, tickets

    ticket = tickets.create(project, title="First", words="w", kind="idea")
    gitio.commit_to_main(project, {f"{tickets.ticket_dir(ticket)}/status.yml": b": : :\n"},
                         "break it")

    check = by_name(doctor.run_checks(), "tickets readable")
    assert check.status == doctor.FAIL and "0001-first" in check.detail


def test_a_ticket_left_unpushed_fails(tmp_home: Path, identity, stub_claude):
    from taller import tickets

    project = support.new_project(origin=str(tmp_home / "no-such-remote.git"))
    tickets.create(project, title="Stuck", words="w", kind="idea")

    check = by_name(doctor.run_checks(), "tickets readable")
    assert check.status == doctor.FAIL and "0001" in check.detail
    assert "remote is reachable" in check.fix
