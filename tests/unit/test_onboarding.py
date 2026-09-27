"""onboarding.py and prompter.py — the twelve questions, resumable, and the brief."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import support
from taller import catalogue, onboarding, paths
from taller.prompter import ScriptedPrompter, UnscriptedQuestion

SHEET = {
    "q1": "Tracks which neighbour has borrowed which shared tool.",
    "q2": "A marketplace: nothing is bought, sold or rented.",
    "q3": "Knowing who has which tool right now.",
    "q4": "2",
    "q5": "",                      # Enter takes the default
    "q6": "",
    "q7": "Tools, neighbours and loans.",
    "q8": "n",
    "q9": "1",
    "q10": "1",
    "q11": "",
    "q12": ["List the tools", "Record a loan", "Show who has what"],
}


def test_twelve_questions_in_four_rounds_with_no_default_on_the_costly_two():
    assert [q.id for q in onboarding.QUESTIONS] == [f"q{n}" for n in range(1, 13)]
    assert [q.round for q in onboarding.QUESTIONS] == [1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4, 4]
    assert onboarding.BY_ID["q4"].default is None
    assert onboarding.BY_ID["q8"].default is None


def test_a_full_interview_yields_create_project_answers(tmp_home: Path):
    prompter = ScriptedPrompter(SHEET)

    answers = onboarding.run("toolshed", prompter)

    prompter.assert_all_used()
    assert answers == {
        "what_it_does": SHEET["q1"],
        "what_it_is_not": SHEET["q2"],
        "must_never_break": SHEET["q3"],
        "users": "team",
        "reach": "this machine",
        "phone": False,
        "stores": SHEET["q7"],
        "sensitive_data": False,
        "profile": "flask-sqlite",
        "brand": "none",
        "deploy": "local",
        "first_version": SHEET["q12"],
    }
    assert any("Round 4 of 4" in line for line in prompter.said)


def test_every_answer_is_saved_as_given_so_a_dead_session_resumes(tmp_home: Path):
    partial = {key: value for key, value in SHEET.items() if key in ("q1", "q2", "q3")}
    with pytest.raises(UnscriptedQuestion):
        onboarding.run("toolshed", ScriptedPrompter(partial))

    saved = yaml.safe_load(paths.onboarding("toolshed").read_text(encoding="utf-8"))
    assert list(saved) == ["what_it_does", "what_it_is_not", "must_never_break"]

    rest = {key: value for key, value in SHEET.items() if key not in partial}
    prompter = ScriptedPrompter({"resume": "", **rest})
    answers = onboarding.run("toolshed", prompter)

    prompter.assert_all_used()
    assert "q1" not in prompter.asked
    assert answers["what_it_does"] == SHEET["q1"]


def test_declining_to_resume_starts_again(tmp_home: Path):
    onboarding.save_progress("toolshed", {"what_it_does": "Something old."})

    answers = onboarding.run("toolshed", ScriptedPrompter({"resume": "n", **SHEET}))

    assert answers["what_it_does"] == SHEET["q1"]


def test_invalid_input_is_asked_again_with_the_reason(tmp_home: Path):
    prompter = ScriptedPrompter({**SHEET, "q4": ("7", "", "public"), "q8": ("maybe", "y"),
                                 "q1": ("   ", SHEET["q1"])})

    answers = onboarding.run("toolshed", prompter)

    assert answers["users"] == "public"
    assert answers["sensitive_data"] is True
    assert any("choose a number" in line for line in prompter.said)
    assert any("y or n" in line for line in prompter.said)
    assert any("answer is needed" in line for line in prompter.said)


def test_an_empty_first_version_is_refused(tmp_home: Path):
    prompter = ScriptedPrompter({**SHEET, "q12": ([], ["   ", "Record a loan"])})

    assert onboarding.run("toolshed", prompter)["first_version"] == ["Record a loan"]


def test_a_scripted_prompter_refuses_what_it_was_not_given_and_what_it_did_not_use():
    prompter = ScriptedPrompter({"q1": "x", "q99": "left over"})
    assert prompter.ask("q1", "?") == "x"
    with pytest.raises(UnscriptedQuestion):
        prompter.ask("q2", "?")
    with pytest.raises(AssertionError, match="q99"):
        prompter.assert_all_used()


def test_the_profile_picker_lists_the_hub_first_then_the_catalogue(tmp_home: Path):
    empty_hub = onboarding.profile_choices()
    assert [value for value, _ in empty_hub] == ["flask-sqlite", "python-packaged",
                                                 "static-site"]
    # Plain words first, the technical name after, for someone who knows it.
    assert empty_hub[0][1] == "A web app with its own database, used in a browser  [flask-sqlite]"

    catalogue.install_profile("static-site")
    assert onboarding.profile_choices()[0][0] == "static-site"


def test_the_brand_picker_always_offers_none_and_new(tmp_home: Path):
    assert onboarding.brand_choices() == [("none", "none"), (onboarding.NEW_BRAND, "new brand…")]
    support.make_brand("harbour")
    assert ("harbour", "harbour") in onboarding.brand_choices()


def test_new_brand_hands_over_and_its_slug_becomes_the_answer(tmp_home: Path):
    created = []

    def new_brand(prompter):
        created.append(True)
        support.make_brand("harbour")
        return "harbour"

    answers = onboarding.run("toolshed", ScriptedPrompter({**SHEET, "q10": "2"}),
                             new_brand=new_brand)

    assert created and answers["brand"] == "harbour"


def test_a_packaged_program_defaults_to_no_brand(tmp_home: Path):
    answers = onboarding.run("toolshed", ScriptedPrompter({**SHEET, "q9": "2", "q10": ""}))

    assert (answers["profile"], answers["brand"]) == ("python-packaged", "none")


def test_edit_changes_one_answer_and_keeps_the_rest(tmp_home: Path):
    answers = onboarding.run("toolshed", ScriptedPrompter(SHEET))

    onboarding.edit("toolshed", ScriptedPrompter({"q7": "Only tools."}), answers, 7)

    assert answers["stores"] == "Only tools."
    assert answers["what_it_does"] == SHEET["q1"]
    assert onboarding.load_progress("toolshed")["stores"] == "Only tools."


def test_the_brief_is_escaped_self_contained_and_shows_the_swatch(tmp_home: Path):
    support.make_brand("harbour")
    answers = onboarding.run("toolshed", ScriptedPrompter(
        {**SHEET, "q1": "Tracks <script>alert(1)</script> loans", "q10": "2"}))

    page = onboarding.write_brief("toolshed", answers).read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert "#1b365d" in page, "the brand swatch is missing"
    assert "Record a loan" in page and "Knowing who has which tool" in page
    assert "http://" not in page and "https://" not in page


def test_the_interview_writes_nothing_but_its_answers_file(tmp_home: Path):
    before = support.tree_mtimes(tmp_home)

    answers = onboarding.run("toolshed", ScriptedPrompter(SHEET))
    onboarding.write_brief("toolshed", answers)

    changed = {path for path, stamp in support.tree_mtimes(tmp_home).items()
               if before.get(path) != stamp}
    assert changed == {str(paths.onboarding("toolshed")), str(paths.onboarding_brief("toolshed"))}
