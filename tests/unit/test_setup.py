"""hub.py and `taller setup` rounds 1 and 5 (spec 4.7, 11.1, 13.2)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

import support
from taller import config, discovery, hub, paths
from taller.commands import setup
from taller.prompter import ScriptedPrompter

SIGNED_IN = """github.com
  ✓ Logged in to github.com account someone (keyring)
  - Token: gho_************************************
  - Token scopes: 'gist', 'read:org', 'repo'
"""


@pytest.fixture
def gh(monkeypatch: pytest.MonkeyPatch):
    """Stand-in for `gh`; a test sets `.result` to what it should return."""
    class Fake:
        result = subprocess.CompletedProcess([], 0, SIGNED_IN, "")
    monkeypatch.setattr(discovery, "_run_gh", lambda args: Fake.result)
    return Fake


def commits(root: Path) -> list[str]:
    completed = subprocess.run(["git", "-C", str(root), "log", "--format=%s"],
                               capture_output=True, text=True)
    return completed.stdout.splitlines() if completed.returncode == 0 else []


# --- hub.py ------------------------------------------------------------------

def test_the_hub_becomes_a_local_git_repository_on_main(tmp_home: Path, identity):
    hub.ensure_repo()
    hub.ensure_repo()                                   # idempotent

    root = paths.hub()
    branch = subprocess.run(["git", "-C", str(root), "symbolic-ref", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    assert branch == "main"
    remotes = subprocess.run(["git", "-C", str(root), "remote"],
                             capture_output=True, text=True).stdout.strip()
    assert remotes == "", "a hub remote is the owner's decision (13.2)"


def test_commit_records_a_change_and_skips_an_empty_one(tmp_home: Path, identity):
    hub.update_config({"thresholds": {"max_file_lines": 400}})

    assert hub.commit("first") is True
    assert hub.commit("nothing") is False
    assert commits(paths.hub()) == ["first"]
    assert config.hub_sha() != ""


def test_update_config_keeps_every_other_key(tmp_home: Path):
    support.write(paths.hub_config(), yaml.safe_dump(
        {"thresholds": {"max_file_lines": 400}, "language": None}))

    hub.update_config({"language": {"code": "en", "ui": "es", "commits": "en"}})

    data = hub.read_config()
    assert data["thresholds"] == {"max_file_lines": 400}
    assert data["language"] == {"code": "en", "ui": "es", "commits": "en"}


# --- round 1: connect --------------------------------------------------------

def test_gh_signed_in_reports_the_account_and_the_missing_scope(tmp_home: Path, gh):
    status = discovery.gh_auth_status()

    assert status["account"] == "someone"
    assert status["missing"] == ["workflow"]
    assert "gh auth refresh -s workflow" in status["message"]
    assert "gho_" not in status["message"]


@pytest.mark.parametrize("result, phrase", [
    (None, "not installed"),
    (subprocess.CompletedProcess([], 1, "", "You are not logged into any GitHub hosts."),
     "not signed in"),
])
def test_gh_absent_or_signed_out_is_reported_not_fatal(tmp_home: Path, gh, result, phrase):
    gh.result = result

    assert phrase in discovery.gh_auth_status()["message"]


def test_connect_confirms_billing_and_records_a_host(tmp_home: Path, gh):
    prompter = ScriptedPrompter({"setup.billing": "", "setup.host": "vps.example"})

    setup.connect(prompter)

    assert any("subscription" in line for line in prompter.said)
    assert hub.read_config() == {"deploy": {"host": "vps.example"}}


def test_a_corrected_billing_mode_is_written(tmp_home: Path, gh):
    prompter = ScriptedPrompter({"setup.billing": "n", "setup.billing.mode": "2",
                                 "setup.host": ""})

    setup.connect(prompter)

    assert hub.read_config() == {"billing": {"mode": "api"}}


# --- round 5: languages ------------------------------------------------------

def test_languages_have_no_default_and_are_validated(tmp_home: Path):
    prompter = ScriptedPrompter({
        "setup.language.code": ("", "English", "en"),
        "setup.language.ui": "none",
        "setup.language.commits": "EN",
    })

    chosen = setup.languages(prompter)

    assert chosen == {"code": "en", "ui": "none", "commits": "en"}
    assert sum("language code" in line for line in prompter.said) == 2
    assert config.load_hub_config()["language"] == chosen


def test_a_second_run_offers_the_current_languages(tmp_home: Path):
    hub.update_config({"language": {"code": "en", "ui": "es", "commits": "en"}})

    chosen = setup.languages(ScriptedPrompter({"setup.language.code": "",
                                               "setup.language.ui": "",
                                               "setup.language.commits": ""}))

    assert chosen == {"code": "en", "ui": "es", "commits": "en"}


def test_the_inline_rounds_set_up_the_hub_and_commit_it(tmp_home: Path, identity, gh):
    assert setup.needed()
    prompter = ScriptedPrompter({"setup.billing": "", "setup.host": "",
                                 "setup.language.code": "en", "setup.language.ui": "es",
                                 "setup.language.commits": "en"})

    setup.run_inline(prompter)

    prompter.assert_all_used()
    assert not setup.needed()
    assert commits(paths.hub()) == ["setup: connection and languages"]
