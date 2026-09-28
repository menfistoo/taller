"""chief.py — `taller ticket run`: one ticket, carried until it needs the owner.

The stub `claude` answers per role from a script (`STUB_CLAUDE_SCRIPT`), and an
answer may write files and commit in its working directory - how the
implementer "writes code" here without a model.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest
import yaml

import support
from taller import chief, cli, discovery, hub, locking, tickets
from taller.errors import ConfigError, LockTimeout
from taller.prompter import ScriptedPrompter

CLASSIFY = {"value": {"kind": "bug", "title": "Warning red differs",
                      "summary": "The mismatch warning uses the app's danger colour."}}
EXPLORE_ONE_STYLE = {"value": {"files": ["static/css/app.css"], "adds_or_deletes_files": False,
                               "schema_change": False, "route_change": False,
                               "dependency_change": False, "change_kind": "style",
                               "notes": "One rule in app.css."}}
BUILD_ONE_FILE = {
    "value": {"summary": "Used the danger token.", "commits": []},
    "effects": [{"write": "static/css/app.css", "text": "h1 { color: var(--color-danger); }\n"},
                {"commit": "fix(ui): use the danger token"}],
}
BUILD_TWO_FILES = {
    "value": {"summary": "Changed two files.", "commits": []},
    "effects": [{"write": "static/css/app.css", "text": "h1 { color: red; }\n"},
                {"write": "templates/index.html", "text": "<p>changed</p>\n"},
                {"commit": "fix(ui): two files"}],
}
PLAN = {"value": {"plan_md": "1. Change app.css.\n2. Check the page renders."}}
SUMMARY = {"value": {"summary_md": "One rule in app.css now uses the danger token."}}


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    return support.new_project()


@pytest.fixture
def script(tmp_path: Path, monkeypatch):
    """Install a per-role answer script for the stub."""
    path = tmp_path / "script.json"

    def install(**answers):
        path.write_text(json.dumps(answers), encoding="utf-8")
        monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(path))
    return install


def new_ticket(project: Path) -> int:
    return tickets.create(project, title="Placeholder", words="The warning red is wrong.",
                          kind="idea")["id"]


def on_branch(project: Path, ticket: dict, name: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(project), "cat-file", "blob",
         f"{ticket['branch']}:{tickets.ticket_dir(ticket)}/{name}"],
        capture_output=True, text=True, encoding="utf-8")
    return completed.stdout if completed.returncode == 0 else None


# --- ① classification ----------------------------------------------------------

def test_new_asks_only_the_words_and_the_chief_classifies(project: Path, script):
    script(chief=[CLASSIFY])
    prompter = ScriptedPrompter({})

    code = cli.main(["ticket", "new", "The", "warning", "red", "is", "wrong",
                     "--path", str(project)], prompter)

    assert code == 0, prompter.said
    ticket = tickets.load(project, 1)
    assert (ticket["kind"], ticket["title"]) == ("bug", "Warning red differs")
    assert ticket["chief_session"], "the chief's conversation was not kept"
    body = tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/ticket.md").decode()
    assert "The warning red is wrong" in body


def test_new_falls_back_to_asking_when_the_chief_cannot_answer(project: Path, script):
    script(chief=[{"fail": "Not logged in"}, {"fail": "Not logged in"}])
    prompter = ScriptedPrompter({"ticket.kind": "1", "ticket.title": ""})

    code = cli.main(["ticket", "new", "Fix", "the", "red", "--path", str(project)], prompter)

    assert code == 0 and tickets.load(project, 1)["kind"] == "bug"
    assert any("Not logged in" in line for line in prompter.said)


# --- ② the lane ----------------------------------------------------------------

BASE_FACTS = EXPLORE_ONE_STYLE["value"]


@pytest.mark.parametrize("change, lane", [
    ({}, "fast"),
    ({"adds_or_deletes_files": True}, "full"),
    ({"schema_change": True}, "full"),
    ({"route_change": True}, "full"),
    ({"dependency_change": True}, "full"),
    ({"files": ["a.css", "b.css"]}, "full"),
    ({"change_kind": "other"}, "full"),
    ({"files": ["routes/loans.py"]}, "full"),              # security_sensitive
])
def test_decide_lane(project: Path, change: dict, lane: str):
    from taller import constitution

    decided, reason = chief.decide_lane({**BASE_FACTS, **change}, constitution.resolve(project))

    assert decided == lane and reason


def test_an_owner_fast_override_on_a_security_path_is_refused_naming_the_glob(project, script):
    facts = {**BASE_FACTS, "files": ["routes/loans.py"]}
    script(chief=[CLASSIFY], explorer=[{"value": facts}])
    ticket_id = new_ticket(project)

    with pytest.raises(ConfigError, match=r"routes/\*\*"):
        chief.run(project, ticket_id, lane="fast", say=lambda text: None)


# --- whole runs ----------------------------------------------------------------

def test_a_fast_run_stops_at_review_with_spend_recorded(project: Path, script):
    script(chief=[CLASSIFY], explorer=[EXPLORE_ONE_STYLE], implementer=[BUILD_ONE_FILE],
           summariser=[SUMMARY])
    ticket_id = new_ticket(project)

    ticket = chief.run(project, ticket_id, say=lambda text: None)

    assert (ticket["stage"], ticket["lane"]) == ("review", "fast")
    assert ticket["checkpoints"]["review"] == "pending"
    assert "danger token" in on_branch(project, ticket, "review.md")
    assert ticket["spend"]["weighted_tokens"] > 0
    assert "claude-sonnet-5" in ticket["spend"]["by_model"]
    notes = tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/notes.md").decode()
    assert "phase C" in notes, "the gate pass-through was not noted"


def test_a_full_run_stops_at_design_with_the_plan_on_the_branch(project: Path, script):
    full = {"value": {**BASE_FACTS, "change_kind": "other"}}
    script(chief=[CLASSIFY], explorer=[full], architect=[PLAN])
    ticket_id = new_ticket(project)

    ticket = chief.run(project, ticket_id, say=lambda text: None)

    assert (ticket["stage"], ticket["lane"]) == ("design", "full")
    assert "Change app.css" in on_branch(project, ticket, "plan.md")


def test_promotion_at_build_keeps_the_diff_and_returns_to_design(project: Path, script):
    script(chief=[CLASSIFY], explorer=[EXPLORE_ONE_STYLE], implementer=[BUILD_TWO_FILES],
           architect=[PLAN])
    ticket_id = new_ticket(project)

    ticket = chief.run(project, ticket_id, say=lambda text: None)

    assert (ticket["stage"], ticket["lane"]) == ("design", "full")
    assert ticket["checkpoints"]["design"] == "pending"
    changed = subprocess.run(["git", "-C", str(project), "diff", "--name-only",
                              f"main...{ticket['branch']}"], capture_output=True,
                             text=True).stdout.split()
    assert "templates/index.html" in changed, "the diff was not kept"
    notes = tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/notes.md").decode()
    assert "promoted to full" in notes


def test_a_malformed_answer_is_retried_once_then_blocks(project: Path, script):
    bad = {"value": {"files": "not a list"}}
    script(chief=[CLASSIFY], explorer=[bad, bad])
    ticket_id = new_ticket(project)

    ticket = chief.run(project, ticket_id, say=lambda text: None)

    assert ticket["stage"] == "triage" and ticket["blocked"]
    assert "explorer" in ticket["blocked"]["reason"]


def test_a_malformed_answer_that_is_right_the_second_time_carries_on(project: Path, script):
    script(chief=[CLASSIFY], explorer=[{"value": {"files": 1}}, EXPLORE_ONE_STYLE],
           implementer=[BUILD_ONE_FILE], summariser=[SUMMARY])

    ticket = chief.run(project, new_ticket(project), say=lambda text: None)

    assert ticket["stage"] == "review" and not ticket["blocked"]


def test_an_exhausted_window_blocks_with_the_cli_message(project: Path, script):
    limit = {"fail": "You've reached your usage limit. Resets at 5pm."}
    script(chief=[CLASSIFY], explorer=[limit, limit])
    ticket_id = new_ticket(project)

    ticket = chief.run(project, ticket_id, say=lambda text: None)

    assert ticket["blocked"] and "usage limit" in ticket["blocked"]["reason"]
    assert ticket["spend"]["weighted_tokens"] > 0, "spend already folded was lost"


def test_a_second_run_on_the_same_ticket_fails_on_the_lock(project: Path, script):
    script(chief=[CLASSIFY])
    ticket_id = new_ticket(project)
    held, release = threading.Event(), threading.Event()

    def hold():
        with locking.project_lock("toolshed"):
            held.set()
            release.wait(30)
    holder = threading.Thread(target=hold)
    holder.start()
    held.wait(10)
    try:
        with pytest.raises(LockTimeout):
            chief.run(project, ticket_id, say=lambda text: None)
    finally:
        release.set()
        holder.join()
    assert tickets.load(project, ticket_id)["stage"] == "intake"


def test_budget_stop_blocks_before_dispatching(project: Path, script):
    hub.update_config({"budget": {"per_ticket_warn": 1, "per_ticket_stop": 2}})
    script(chief=[CLASSIFY], explorer=[EXPLORE_ONE_STYLE])
    ticket_id = new_ticket(project)

    ticket = chief.run(project, ticket_id, say=lambda text: None)

    assert ticket["blocked"] and "budget" in ticket["blocked"]["reason"]
    assert ticket["stage"] == "triage", "work went on past the stop"


def test_an_unavailable_model_falls_back_and_is_recorded(project: Path, script, monkeypatch):
    monkeypatch.setenv("STUB_CLAUDE_FAIL_MODEL", "opus")
    full = {"value": {**BASE_FACTS, "change_kind": "other"}}
    script(chief=[CLASSIFY], explorer=[full], architect=[PLAN])

    ticket = chief.run(project, new_ticket(project), say=lambda text: None)

    assert ticket["stage"] == "design" and not ticket["blocked"]
    assert ticket["fallbacks"] == [{"role": "architect", "requested": "opus", "used": "sonnet"}]
