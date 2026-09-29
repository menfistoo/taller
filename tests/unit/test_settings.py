"""settings.py, `taller settings` and `taller brand edit` — one surface, and fan-out.

Spec 5.2 and 4.6: every effective key shows the layer it came from; a change is
written to the right layer, and every project it reaches is refreshed rather
than left stale.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest
import yaml

import support
from taller import cli, constitution, doctor, hub, paths, scaffold, settings
from taller.commands import brand as brand_command
from taller.commands import settings as settings_command
from taller.errors import ConfigError
from taller.prompter import ScriptedPrompter

ANSWERS = {
    "what_it_does": "Lends shared tools.", "what_it_is_not": "A marketplace.",
    "must_never_break": "Who has which tool.", "users": "team", "reach": "a VPN",
    "phone": False, "stores": "Tools.", "sensitive_data": False, "deploy": "local",
    "first_version": ["Record a loan"],
}


@pytest.fixture
def estate(tmp_home: Path, identity, stub_claude, monkeypatch) -> dict[str, Path]:
    monkeypatch.setattr(brand_command, "open_in_browser", lambda page: None)
    hub.update_config({"language": {"code": "en", "ui": "es", "commits": "en"}})
    support.make_brand("harbour")
    hub.commit("setup")
    made = {}
    for name, brand in (("alpha", "harbour"), ("beta", "harbour"), ("gamma", None)):
        made[name] = paths.home() / "projects" / name
        scaffold.create_project(made[name], name=name, profile="flask-sqlite", brand=brand,
                                answers=ANSWERS)
    return made


def row(rows, key):
    return next(r for r in rows if r[0] == key)


def failures() -> list[str]:
    return [c.name for c in doctor.run_checks() if c.status == doctor.FAIL]


def on_main(project: Path, relative: str) -> str:
    return subprocess.run(["git", "-C", str(project), "cat-file", "blob", f"main:{relative}"],
                          capture_output=True, text=True, check=True).stdout


def test_every_key_shows_the_layer_it_came_from(estate):
    support.write(paths.project_config(estate["alpha"]),
                  yaml.safe_dump({"thresholds": {"max_function_lines": 40}}))

    hub_rows = settings.effective()
    assert row(hub_rows, "thresholds.max_file_lines") == ("thresholds.max_file_lines", 800,
                                                           "default")
    assert row(hub_rows, "language.ui")[2] == "hub"
    assert row(hub_rows, "billing.mode") == ("billing.mode", "subscription", "detected")

    project_rows = settings.effective(estate["alpha"])
    assert row(project_rows, "thresholds.max_function_lines")[1:] == (40, "project")
    assert row(project_rows, "paths.brand_tokens")[2] == "profile flask-sqlite"


def test_a_hub_setting_fans_out_to_every_adopted_project(estate):
    touched = settings.set_value("thresholds.max_file_lines", "400")

    assert sorted(name for name, _ in touched) == ["alpha", "beta", "gamma"]
    assert row(settings.effective(), "thresholds.max_file_lines")[1:] == (400, "hub")
    assert '"max_file_lines": 400' in on_main(estate["gamma"], ".taller/resolved.json")
    assert failures() == [], "a hub change left snapshots stale"


def test_a_project_setting_is_one_commit_in_that_project(estate):
    touched = settings.set_value("thresholds.max_file_lines", "300", estate["beta"])

    assert [name for name, _ in touched] == ["beta"]
    assert yaml.safe_load(paths.project_config(estate["beta"]).read_text("utf-8")) == {
        "thresholds": {"max_file_lines": 300}}
    log = subprocess.run(["git", "-C", str(estate["beta"]), "log", "--format=%s", "-2"],
                         capture_output=True, text=True).stdout.splitlines()
    assert log == ["taller: resolve the constitution", "settings: thresholds.max_file_lines"]
    assert failures() == []


def test_an_unknown_key_is_refused(estate):
    with pytest.raises(ConfigError, match="no setting"):
        settings.set_value("thresholds.max_file_line", "400")


def test_an_append_only_list_cannot_lose_an_entry(estate):
    settings.set_value("paths.security_sensitive", '["billing/**"]')
    effective = row(settings.effective(), "paths.security_sensitive")[1]
    assert "billing/**" in effective and ".env*" in effective, "the shipped floor was lost"

    with pytest.raises(ConfigError, match="append-only"):
        settings.set_value("paths.security_sensitive", "[]")
    assert "billing/**" in row(settings.effective(), "paths.security_sensitive")[1]


def test_edit_opens_the_file_then_validates_and_fans_out(estate, monkeypatch):
    def editor(path: Path):
        text = path.read_text(encoding="utf-8")
        path.write_text(text + "thresholds:\n  max_fix_rounds: 3\n", encoding="utf-8")
    monkeypatch.setattr(settings_command, "open_editor", editor)

    assert cli.main(["settings", "edit"], ScriptedPrompter({})) == 0

    assert row(settings.effective(), "thresholds.max_fix_rounds")[1:] == (3, "hub")
    assert failures() == []


def test_the_command_lists_settings(estate):
    prompter = ScriptedPrompter({})

    assert cli.main(["settings"], prompter) == 0
    assert "thresholds.max_file_lines" in prompter.said[-1] and "(default)" in prompter.said[-1]


def test_a_brand_edit_reaches_exactly_the_projects_using_it(estate):
    prompter = ScriptedPrompter({"brand.tokens": ("1", ""), "brand.token.name": "",
                                 "brand.token.value": "#0f7a5a", "brand.intent": "",
                                 "brand.approve": "1"})

    assert brand_command.edit(argparse.Namespace(slug="harbour", no_open=True), prompter) == 0

    assert constitution._resolve_brand("harbour")["tokens"]["--color-primary"] == "#0f7a5a"
    assert "alpha (" in prompter.said[-1] and "beta (" in prompter.said[-1]
    assert "gamma" not in prompter.said[-1]
    for name in ("alpha", "beta"):
        assert "#0f7a5a" in on_main(estate[name], "static/css/tokens.css")
    assert failures() == []
