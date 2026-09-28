"""roles.py — what each role is told, and the shape its answer must have (§3.6.0, §6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from taller import config, inference, roles


def test_the_ten_roles_match_the_tool_table():
    assert set(roles.ROLES) == set(inference.ROLE_TOOLS)
    assert len(roles.ROLES) == 10


@pytest.mark.parametrize("role", sorted(inference.ROLE_TOOLS))
def test_every_role_has_a_definition_starting_with_its_marker(role: str):
    text = roles.definition(role)

    assert text.splitlines()[0] == f"ROLE: {role}"
    assert len(text) > 200, "a definition says who it is, what it may touch, what it answers"


def test_the_brief_is_definition_then_slices(tmp_home: Path):
    ruleset = {"slices": {
        "ux": {"text": "> UX rules.\nButtons say what they do.\n"},
        "security": {"text": "> Security rules.\nNever log a password.\n"},
    }}
    dispatch = inference.Dispatch(role="gate_ux", prompt="p", config=config.load_hub_config(),
                                  ruleset=ruleset)

    brief = inference._brief(dispatch)

    assert brief.splitlines()[0] == "ROLE: gate_ux"
    assert "Buttons say what they do." in brief
    assert "Never log a password." not in brief
    assert brief.index("ROLE: gate_ux") < brief.index("Buttons say what they do.")


def test_an_explicit_system_is_added_after_the_role(tmp_home: Path):
    dispatch = inference.Dispatch(role="chief", prompt="p", config=config.load_hub_config(),
                                  system="Ticket 7 is at triage.")

    brief = inference._brief(dispatch)

    assert brief.startswith("ROLE: chief") and brief.rstrip().endswith("Ticket 7 is at triage.")


GOOD = {
    "chief": {"kind": "bug", "title": "Red mismatch", "summary": "The warning red differs."},
    "explorer": {"files": ["templates/a.html"], "adds_or_deletes_files": False,
                 "schema_change": False, "route_change": False, "dependency_change": False,
                 "change_kind": "style", "notes": "one template"},
    "architect": {"plan_md": "## Plan\n1. Change the colour."},
    "implementer": {"summary": "Changed the colour.", "commits": ["abc123"]},
    "summariser": {"summary_md": "One template changed."},
}


@pytest.mark.parametrize("role", sorted(GOOD))
def test_check_accepts_a_good_answer(role: str):
    assert roles.check(role, GOOD[role]) is None


@pytest.mark.parametrize("role, answer, word", [
    ("chief", {"kind": "bug", "title": "t"}, "summary"),
    ("chief", {"kind": "wish", "title": "t", "summary": "s"}, "kind"),
    ("explorer", {**GOOD["explorer"], "files": "templates/a.html"}, "files"),
    ("explorer", {**GOOD["explorer"], "change_kind": "vibes"}, "change_kind"),
    ("architect", "just prose, not an object", "object"),
    ("implementer", {"summary": "s", "commits": [1, 2]}, "commits"),
])
def test_check_names_what_is_wrong(role: str, answer, word: str):
    problem = roles.check(role, answer)

    assert problem and word in problem


def test_definitions_ship_in_the_wheel():
    text = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")

    assert '"agents/*.md"' in text
