"""Taller's jobs leave her connected services and plugins out (phase G2, Task 1).

Every request a job makes carries her whole Claude Code setup unless told
otherwise: measured on her machine, about a quarter of each request's starting
weight, and her Gmail, Drive and Calendar within reach of every job. None of it
is needed for the work. `--strict-mcp-config` with no `--mcp-config` loads no
connected service; `--setting-sources project,local` leaves her user settings
and plugins out while a project's own `.claude/settings.json` still applies.
Never `--bare` (it skips the subscription's sign-in) and never `--safe-mode`
(it also drops the project's CLAUDE.md, skills and hooks).
"""

from __future__ import annotations

from taller import cli_probe, config, doctor, hub, inference


def dispatch(**over) -> inference.Dispatch:
    role = over.pop("role", "explorer")
    return inference.Dispatch(role=role, prompt="hello", config=over.pop("cfg", None)
                              or config.load_hub_config(), **over)


def test_by_default_a_job_loads_no_connected_services_and_no_plugins(tmp_home):
    argv, _ = inference._build(dispatch(), "claude")

    assert "--strict-mcp-config" in argv and "--mcp-config" not in argv
    assert argv[argv.index("--setting-sources") + 1] == "project,local"


def test_it_can_be_turned_off(tmp_home):
    hub.update_config({"dispatch": {"leave_out_my_setup": False}})

    argv, _ = inference._build(dispatch(), "claude")

    assert "--strict-mcp-config" not in argv and "--setting-sources" not in argv


def test_never_bare_and_never_safe_mode(tmp_home):
    argv, _ = inference._build(dispatch(), "claude")

    assert "--bare" not in argv and "--safe-mode" not in argv


def test_the_flags_come_before_the_brief(tmp_home):
    """The Windows stub shim drops everything after the brief's line breaks."""
    argv, _ = inference._build(dispatch(), "claude")

    brief = argv.index("--append-system-prompt")
    assert argv.index("--strict-mcp-config") < brief and argv.index("--setting-sources") < brief


def test_a_cli_without_the_flags_is_reported(tmp_home):
    assert {"--strict-mcp-config", "--setting-sources"} <= set(cli_probe.REQUIRED_FLAGS)


def test_doctor_checks_sign_in_the_way_jobs_run(tmp_home, stub_claude):
    doctor.run_checks(live=True)

    dispatched = [call for call in stub_claude.calls() if "-p" in call]
    assert dispatched and "--strict-mcp-config" in dispatched[-1]
    assert "--setting-sources" in dispatched[-1]


def test_it_ships_on(tmp_home):
    assert config.SHIPPED_DEFAULTS["dispatch"]["leave_out_my_setup"] is True
