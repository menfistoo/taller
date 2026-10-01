"""Her words: the machine's state, said the way she would say it.

The owner is not an engineer. Nothing she reads may name the machine - no stage
numerals, no lanes, no gates, no rule ids, no severities. Every word the plain
front shows lives in `cockpit/words.py`, and `cockpit/plain.py` is the only
thing that turns a ticket into those words.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import support
from cockpit import plain, words
from taller import discovery, gates, tickets

FORBIDDEN = ("gate", "verdict", "lane", "checkpoint", "blocker", "severity",
             "branch", "commit", "sha", "sync", "worktree", "stage")


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    return support.new_project()


def test_every_rule_taller_can_report_has_a_sentence():
    assert set(words.FINDINGS) == set(gates.RULES)


def test_no_sentence_reads_like_a_machine():
    for text in [*words.FINDINGS.values(), *words.DOING.values(), *words.STATES.values(),
                 *words.GROUPS.values()]:
        assert not [word for word in FORBIDDEN if word in text.lower()], text


def test_every_stage_says_what_it_is_doing():
    assert set(words.DOING) == set(tickets.STAGES)


def test_a_rule_with_no_sentence_is_said_by_its_check_not_by_its_message():
    """A rule added later, or one a model-run check named itself, has no sentence
    here; its message is written for an engineer, so the page says which kind of
    check found something, and the detailed view keeps the message."""
    said = plain.sentence({"rule": "size.something-new", "severity": "MEDIUM",
                           "message": "Two files look the same.", "file": "", "line": 0})

    assert said == words.CHECK_FOUND["other"]
    assert "size." not in said


def test_a_finding_says_where_it_is():
    said = plain.sentence({"rule": "brand.hardcoded-color", "severity": "HIGH",
                           "message": "#dc3545 in a stylesheet", "file": "static/css/app.css",
                           "line": 12})

    assert said.startswith("A colour was written straight into the page")
    assert said.endswith("— in static/css/app.css, line 12")


def test_a_finding_with_a_file_but_no_line_names_just_the_file():
    said = plain.sentence({"rule": "size.file-too-long", "severity": "MEDIUM",
                           "message": "1,100 lines", "file": "loans/ledger.py", "line": 0})

    assert said == "One file is getting long — in loans/ledger.py"


def test_the_four_states(project):
    tickets.create(project, title="A thing", words="Do it.", kind="bug")
    ticket = tickets.load(project, 1)

    working = plain.state_of({**ticket, "stage": "build"})
    needs_you = plain.state_of({**ticket, "stage": "review"})
    stopped = plain.state_of({**ticket, "stage": "gates",
                              "blocked": {"reason": "tests failed", "at_stage": 5,
                                          "since": "2026-09-29T10:00:00"}})
    done = plain.state_of({**ticket, "stage": "close", "outcome": "done"})

    assert (working, needs_you, stopped, done) == ("working", "needs_you", "stopped", "done")


def test_waiting_to_publish_needs_her(project):
    tickets.create(project, title="A thing", words="Do it.", kind="bug")
    ticket = {**tickets.load(project, 1), "stage": "pr", "branch": "ticket/0001-a-thing"}

    assert plain.state_of(ticket) == "working"
    assert plain.state_of(ticket, waiting_to_publish=True) == "needs_you"
    assert plain.doing(ticket, waiting_to_publish=True) == words.READY_TO_PUBLISH


def test_what_it_is_doing_is_a_sentence(project):
    tickets.create(project, title="A thing", words="Do it.", kind="bug")
    ticket = tickets.load(project, 1)

    assert plain.doing({**ticket, "stage": "build"}) == "Making the change"


def test_a_plan_still_being_written_is_not_waiting_for_her(project):
    """Every checkpoint starts `pending`: that alone is not "needs you"."""
    tickets.create(project, title="A thing", words="Do it.", kind="bug")
    at_design = {**tickets.load(project, 1), "stage": "design"}

    assert plain.state_of(at_design, ready=False) == "working"
    assert plain.doing(at_design, ready=False) == "Writing a plan for you to read"
    assert plain.state_of(at_design, ready=True) == "needs_you"
    assert plain.doing(at_design, ready=True) == "A plan is ready for you to read"


def test_findings_split_into_worth_a_look_and_small_without_naming_severity():
    found = [{"rule": "tests.failed", "severity": "BLOCKER", "message": "", "file": "", "line": 0},
             {"rule": "brand.hardcoded-color", "severity": "HIGH", "message": "", "file": "", "line": 0},
             {"rule": "size.file-too-long", "severity": "MEDIUM", "message": "", "file": "", "line": 0},
             {"rule": "size.duplicate-block", "severity": "LOW", "message": "", "file": "", "line": 0}]

    look, small = plain.split(found)

    assert look == ["Some tests did not pass",
                    "A colour was written straight into the page instead of using your brand's"]
    assert small == ["One file is getting long", "The same lines appear in more than one place"]


def test_an_overridden_finding_is_not_worth_bothering_her_with():
    """A NIT from an override is a deviation she already allowed (spec 4.5)."""
    look, small = plain.split([{"rule": "size.file-too-long", "severity": "NIT",
                                "message": "", "file": "", "line": 0,
                                "overridden": "being split"}])

    assert look == [] and small == []


def test_a_stopped_thing_says_what_it_was_doing_when_it_stopped(project):
    tickets.create(project, title="A thing", words="Do it.", kind="bug")
    stopped = {**tickets.load(project, 1), "stage": "smoke",
               "blocked": {"reason": "smoke.timeout", "at_stage": 6, "since": "2026-09-29T10:00:00"}}

    assert plain.doing(stopped) == "Stopped while starting your app to see that it still runs"


def test_written_text_reads_as_text_not_as_markup():
    """Plans and summaries arrive as Markdown; `##` and `**` are the machine
    showing through. The page shows headings, bold, lists - and nothing else."""
    from cockpit import prose

    shown = str(prose.render("## What it delivers\n\nA **new** check.\n\n- one\n- two\n"
                             "\nUses `taller ci`.\n"))

    assert "<h3>What it delivers</h3>" in shown
    assert "<strong>new</strong>" in shown
    assert "<li>one</li>" in shown and "<li>two</li>" in shown
    assert "<code>taller ci</code>" in shown
    assert "##" not in shown and "**" not in shown


def test_written_text_cannot_inject_anything():
    from cockpit import prose

    shown = str(prose.render("<script>alert(1)</script> **<b>x</b>**"))

    assert "<script>" not in shown and "<b>" not in shown
    assert "&lt;script&gt;" in shown
