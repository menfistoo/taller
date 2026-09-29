"""Two gaps found by the first real ticket (2026-09-28, the sandbox project).

1. A hub profile installed by an older Taller keeps its old settings for ever -
   deliberately, because an installed profile is the owner's to edit - and
   nothing said so. It surfaced as a blocked ticket. Doctor now reports it, and
   `taller profiles update <name>` brings one up to date.
2. The smoke gate said only "did not answer within 30 s" when the app had in
   fact started on its own hardcoded port, ignoring the one the gate allocated.
   The message now says which port it took, so the owner knows what to fix.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import support
from taller import catalogue, cli, discovery, doctor, paths
from taller.commands import profiles as profiles_command
from taller.gates import smoke
from taller.prompter import ScriptedPrompter

from test_gates_smoke import app


@pytest.fixture
def hub(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    return tmp_home


def install_an_old_profile(name: str = "flask-sqlite") -> dict:
    """The profile as an older Taller installed it: no smoke port wiring."""
    catalogue.install_profile(name)
    path = catalogue.hub_profile_path(name)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["smoke"] = {"kind": "http", "boot": "python run_local.py",
                     "ready": "http://127.0.0.1:5000/", "timeout_s": 30, "routes": ["/"]}
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return data


def by_name(checks, fragment: str):
    found = [c for c in checks if fragment in c.name]
    assert len(found) == 1, [c.name for c in checks]
    return found[0]


# --- gap 1: doctor reports a profile that predates this Taller -------------------------

def test_doctor_reports_a_profile_that_predates_this_taller(hub):
    install_an_old_profile()

    check = by_name(doctor.run_checks(), "profile flask-sqlite is current")

    assert check.status == doctor.FAIL
    assert "smoke" in check.detail
    assert "taller profiles update flask-sqlite" in check.fix


def test_doctor_passes_on_a_profile_this_taller_installed(hub):
    catalogue.install_profile("flask-sqlite")

    assert by_name(doctor.run_checks(), "profile flask-sqlite is current").status == doctor.PASS


def test_an_owner_edit_is_not_called_stale(hub):
    catalogue.install_profile("flask-sqlite")
    path = catalogue.hub_profile_path("flask-sqlite")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["smoke"]["timeout_s"] = 90                       # hers: a slower machine
    data["paths"]["security_sensitive"].append("payments/**")
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    assert by_name(doctor.run_checks(), "profile flask-sqlite is current").status == doctor.PASS


def test_what_is_missing_names_the_settings(hub):
    install_an_old_profile()

    missing = catalogue.profile_gaps("flask-sqlite")

    assert missing == ["smoke.data", "smoke.database", "smoke.env.PORT",
                       "smoke.env.DATABASE"]
    # `ready` is not listed: she has a value for it, and her values are never
    # overwritten. The contradiction that leaves is doctor's to report, below.


# --- gap 1: the command that fixes it --------------------------------------------------

def test_profiles_update_brings_a_profile_up_to_date_and_refreshes_its_projects(hub):
    install_an_old_profile()
    project = support.new_project()
    prompter = ScriptedPrompter({"profiles.update": "y"})

    code = cli.main(["profiles", "update", "flask-sqlite"], prompter)

    said = "\n".join(prompter.said)
    assert code == 0, said
    assert catalogue.profile_gaps("flask-sqlite") == []
    assert "smoke.env.PORT" in said and "toolshed" in said
    assert "amend: " in support.git(paths.hub(), "log", "-1", "--format=%s")


def test_profiles_update_keeps_the_owners_own_settings(hub):
    install_an_old_profile()
    path = catalogue.hub_profile_path("flask-sqlite")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["smoke"]["timeout_s"] = 90
    data["paths"]["security_sensitive"].append("payments/**")
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    assert cli.main(["profiles", "update", "flask-sqlite"],
                    ScriptedPrompter({"profiles.update": "y"})) == 0

    updated = catalogue.read_hub_profile("flask-sqlite")
    assert updated["smoke"]["timeout_s"] == 90                     # hers is kept
    assert "payments/**" in updated["paths"]["security_sensitive"]
    assert updated["smoke"]["env"]["PORT"] == "$TALLER_SMOKE_PORT"  # the new setting arrives


def test_nothing_to_update_says_so(hub):
    catalogue.install_profile("flask-sqlite")
    prompter = ScriptedPrompter({})

    code = cli.main(["profiles", "update", "flask-sqlite"], prompter)

    assert code == 0 and "already current" in "\n".join(prompter.said)


def test_the_owner_can_say_no(hub):
    install_an_old_profile()

    code = cli.main(["profiles", "update", "flask-sqlite"],
                    ScriptedPrompter({"profiles.update": "n"}))

    assert code == 1 and catalogue.profile_gaps("flask-sqlite") != []


def test_profiles_list_shows_which_are_current(hub):
    install_an_old_profile()
    prompter = ScriptedPrompter({})

    assert cli.main(["profiles", "list"], prompter) == 0
    said = "\n".join(prompter.said)
    assert "flask-sqlite" in said and "out of date" in said


# --- gap 2: the app took its own port ---------------------------------------------------

def test_an_app_that_ignores_the_port_is_named_not_just_timed_out(tmp_path):
    worktree, rules = app(tmp_path, "wrongport")     # takes 5000 whatever it is told
    rules["smoke"]["timeout_s"] = 5

    verdict = smoke.run(worktree, rules)

    hits = [f for f in verdict["findings"] if f["rule"] == "smoke.timeout"]
    assert [h["severity"] for h in hits] == ["HIGH"]
    message = hits[0]["message"]
    assert "5000" in message and "is not reading" in message and "$TALLER_SMOKE_PORT" in message
    assert hits[0]["fix_hint"] and "PORT" in hits[0]["fix_hint"]


def test_a_ready_url_on_a_fixed_port_is_reported_as_a_contradiction(hub):
    """What `profiles update` cannot fix: her own `ready` value, left from the old
    default, would poll 5000 while the app starts on the allocated port."""
    install_an_old_profile()
    catalogue.merge_into_hub_profile("flask-sqlite")        # what `update` writes
    config = catalogue.read_hub_profile("flask-sqlite")["smoke"]

    found = " ".join(smoke.problems(config))

    assert "ready" in found and "5000" in found
    assert "$TALLER_SMOKE_PORT" in found


def test_a_slow_app_still_reads_as_a_plain_timeout(tmp_path):
    worktree, rules = app(tmp_path, "slow")
    rules["smoke"]["timeout_s"] = 3

    verdict = smoke.run(worktree, rules)

    hits = [f for f in verdict["findings"] if f["rule"] == "smoke.timeout"]
    assert hits and "is not reading" not in hits[0]["message"]
