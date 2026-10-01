"""Her own rules survive a change to what the project is.

`taller project brief` rewrote `product.md` and `never.md` wholesale from the
twelve answers, so anything written there by hand - or by a page that invites her
to write rules - vanished the next time one answer changed. Her rules now live in
their own section, which the answers never touch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import support
from taller import own_rules, paths, scaffold
from taller.commands import project as project_command
from taller.errors import ConfigError, NotOnMain
from taller.prompter import ScriptedPrompter

from test_project_brief import ANSWERS, args, slice_text


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude) -> Path:
    support.write(paths.hub_config(), yaml.safe_dump(
        {"language": {"code": "en", "ui": "es", "commits": "en"}}))
    target = paths.home() / "projects" / "toolshed"
    scaffold.create_project(target, name="toolshed", profile="flask-sqlite",
                            brand=None, answers=ANSWERS)
    return target


def resolved(project: Path) -> str:
    return json.dumps(json.loads((project / ".taller" / "resolved.json").read_text("utf-8")))


def test_changing_an_answer_keeps_her_own_rules(project):
    own_rules.add(project, "always", "Take the list from the returns book.",
                  "The slips are often late.")
    own_rules.add(project, "never", "Show a neighbour's phone number.")

    prompter = ScriptedPrompter({"brief.edit": ("3", ""), "q3": "Knowing who has which tool.",
                                 "brief.approve": ""})
    assert project_command.brief(args(project), prompter) == 0

    kept = own_rules.read(project)
    assert [rule["text"] for rule in kept["always"]] == ["Take the list from the returns book."]
    assert [rule["text"] for rule in kept["never"]] == ["Show a neighbour's phone number."]
    assert "Knowing who has which tool." in slice_text(project, "product")


def test_a_rule_reaches_the_rules_the_checks_read(project):
    own_rules.add(project, "never", "Show a neighbour's phone number.")

    assert "Show a neighbour's phone number." in resolved(project)


def test_a_rule_is_kept_with_why_and_when(project):
    own_rules.add(project, "always", "Take the list from the returns book.",
                  "The slips are often late.")

    rule = own_rules.read(project)["always"][0]

    assert rule["why"] == "The slips are often late."
    assert len(rule["added"]) == 10 and rule["added"][4] == "-"


def test_a_rule_without_a_reason_is_fine_and_says_so(project):
    own_rules.add(project, "always", "Show amounts with two decimals.")

    rule = own_rules.read(project)["always"][0]

    assert rule["text"] == "Show amounts with two decimals." and rule["why"] == ""


def test_removing_a_rule_needs_a_reason(project):
    own_rules.add(project, "always", "Show amounts with two decimals.")

    with pytest.raises(ConfigError):
        own_rules.remove(project, "always", 0, "  ")
    own_rules.remove(project, "always", 0, "The totals are whole numbers now.")

    assert own_rules.read(project)["always"] == []


def test_a_rule_is_refused_while_the_project_is_on_a_ticket_branch(project):
    support.git(project, "checkout", "--quiet", "-b", "ticket/0001-something")

    with pytest.raises(NotOnMain) as refused:
        own_rules.add(project, "always", "Show amounts with two decimals.")

    assert "main" in str(refused.value)


def test_an_empty_rule_is_refused(project):
    with pytest.raises(ConfigError):
        own_rules.add(project, "never", "   ")


def test_a_project_with_no_rules_of_her_own_reads_empty(project):
    assert own_rules.read(project) == {"always": [], "never": []}
