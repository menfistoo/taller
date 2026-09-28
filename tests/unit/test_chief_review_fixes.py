"""Findings of the Phase B whole-branch review, each pinned by a test.

C1 a ⑦ rejection stuck at ② on a changed lane; C2 a ③ rejection dead end; I1 roles
briefed without the change or the rejection reason; I2 `run` overwriting the
owner's own naming; I3 an approved checkpoint asked for again; I4 uncommitted
implementer edits; I5 a blank title; I6 security globs missing root-level and
nested files; I7 Ctrl-C orphaning the CLI; I9 a `.cmd` launcher truncating the
role's instructions.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import support
from taller import chief, cli, config, constitution, discovery, globs, inference, roles, tickets
from taller.prompter import ScriptedPrompter

CLASSIFY = {"value": {"kind": "bug", "title": "Warning red differs", "summary": "Match it."}}
STYLE = {"files": ["static/css/app.css"], "adds_or_deletes_files": False, "schema_change": False,
         "route_change": False, "dependency_change": False, "change_kind": "style",
         "notes": "One rule."}
TWO_FILES = {**STYLE, "files": ["static/css/app.css", "templates/index.html"]}
BUILD = {"value": {"summary": "Changed app.css.", "commits": []},
         "effects": [{"write": "static/css/app.css", "text": "h1 { color: blue; }\n"},
                     {"commit": "fix(ui): colour"}]}
PLAN = {"value": {"plan_md": "1. First plan."}}
PLAN_2 = {"value": {"plan_md": "1. Second plan, with the export."}}
SUMMARY = {"value": {"summary_md": "Summary."}}


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    return support.new_project()


@pytest.fixture
def script(tmp_path: Path, monkeypatch):
    path = tmp_path / "script.json"

    def install(**answers):
        path.write_text(json.dumps(answers), encoding="utf-8")
        monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(path))
    return install


def quiet(text: str) -> None:
    pass


def new_ticket(project: Path) -> int:
    return tickets.create(project, title="Placeholder", words="Fix the warning red.",
                          kind="idea", named_by=None)["id"]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


# --- C1 ----------------------------------------------------------------------

def test_a_review_rejection_runs_on_when_the_lane_decision_grows(project: Path, script):
    script(chief=[CLASSIFY], explorer=[{"value": STYLE}, {"value": TWO_FILES}],
           implementer=[BUILD], summariser=[SUMMARY], architect=[PLAN])
    ticket_id = new_ticket(project)
    chief.run(project, ticket_id, say=quiet)                  # fast, stops at review
    tickets.reject(project, ticket_id, "It should also change the template.")

    ticket = chief.run(project, ticket_id, say=quiet)

    assert not ticket["blocked"] and ticket["lane"] == "full"
    assert ticket["stage"] == "design"


# --- C2 ----------------------------------------------------------------------

def test_a_rejected_plan_is_rewritten_with_the_reason(project: Path, script, stub_claude):
    full = {**STYLE, "change_kind": "other"}
    script(chief=[CLASSIFY], explorer=[{"value": full}], architect=[PLAN, PLAN_2])
    ticket_id = new_ticket(project)
    chief.run(project, ticket_id, say=quiet)                  # stops at design
    tickets.reject(project, ticket_id, "Plan misses the export.")
    tickets.resume(project, ticket_id)

    ticket = chief.run(project, ticket_id, say=quiet)

    assert ticket["stage"] == "design" and ticket["checkpoints"]["design"] == "pending"
    plan = git(project, "cat-file", "blob",
               f"{ticket['branch']}:{tickets.ticket_dir(ticket)}/plan.md")
    assert "Second plan" in plan


# --- I1 ----------------------------------------------------------------------

def test_the_summariser_sees_the_change_and_the_architect_the_rejection(project: Path):
    ticket_id = new_ticket(project)
    tickets.write(project, tickets.load(project, ticket_id), "note",
                  note="design rejected: Plan misses the export.")

    text = chief._context(project, tickets.load(project, ticket_id))

    assert "Plan misses the export." in text and "Fix the warning red." in text


def test_the_diff_reaches_the_prompt(project: Path, script):
    script(chief=[CLASSIFY], explorer=[{"value": STYLE}], implementer=[BUILD],
           summariser=[SUMMARY])
    ticket_id = new_ticket(project)
    chief.run(project, ticket_id, say=quiet)
    ticket = tickets.load(project, ticket_id)

    text = chief._change(project, ticket)

    assert "static/css/app.css" in text and "color: blue" in text


# --- I2 ----------------------------------------------------------------------

def test_run_keeps_the_owners_own_naming(project: Path, script):
    # The chief has an answer ready: if run asked it, it would overwrite the naming.
    script(chief=[CLASSIFY], explorer=[{"value": STYLE}], implementer=[BUILD],
           summariser=[SUMMARY])
    ticket_id = tickets.create(project, title="My own title", words="w", kind="feature")["id"]

    ticket = chief.run(project, ticket_id, say=quiet)

    assert ticket["stage"] == "review" and not ticket["blocked"]
    assert (ticket["kind"], ticket["title"]) == ("feature", "My own title")


# --- I3 ----------------------------------------------------------------------

def test_an_approved_checkpoint_waits_for_the_merge_then_moves_on(project: Path, script):
    full = {**STYLE, "change_kind": "other"}
    script(chief=[CLASSIFY], explorer=[{"value": full}], architect=[PLAN], implementer=[BUILD],
           summariser=[SUMMARY])
    ticket_id = new_ticket(project)
    chief.run(project, ticket_id, say=quiet)                  # design
    tickets.approve(project, ticket_id)
    chief.run(project, ticket_id, say=quiet)                  # review
    tickets.approve(project, ticket_id)
    chief.run(project, ticket_id, say=quiet)                  # staging
    try:
        tickets.approve(project, ticket_id)                   # approved; merge refused
    except Exception:
        pass
    ticket = tickets.load(project, ticket_id)
    git(project, "merge", "--quiet", "--no-edit", ticket["branch"])

    ticket = chief.run(project, ticket_id, say=quiet)

    assert ticket["stage"] == "release"


# --- I4 ----------------------------------------------------------------------

def test_uncommitted_implementer_edits_are_committed_not_called_nothing(project: Path, script):
    uncommitted = {"value": {"summary": "Edited.", "commits": []},
                   "effects": [{"write": "static/css/app.css", "text": "h1 { color: blue; }\n"}]}
    script(chief=[CLASSIFY], explorer=[{"value": STYLE}], implementer=[uncommitted],
           summariser=[SUMMARY])

    ticket = chief.run(project, new_ticket(project), say=quiet)

    assert ticket["stage"] == "review" and not ticket["blocked"]
    assert "uncommitted work from the implementer" in git(project, "log", "--format=%s",
                                                          ticket["branch"])


# --- I5 ----------------------------------------------------------------------

def test_a_blank_title_is_not_a_usable_answer():
    assert roles.check("chief", {"kind": "bug", "title": "   ", "summary": "s"})


# --- I6 ----------------------------------------------------------------------

FLOOR = [".env*", "**/*secret*", "**/*credential*"]


@pytest.mark.parametrize("path", ["secrets.py", "credentials.json", "config/.env.prod",
                                  "app/deep/my_secret_key.txt", ".env"])
def test_the_security_floor_matches_at_any_depth(path: str):
    assert any(globs.match(path, glob) for glob in FLOOR)


@pytest.mark.parametrize("path, glob, expected", [
    ("routes/a.py", "routes/**", True),
    ("src/routes/a.py", "routes/**", False),
    ("migrate_001.py", "migrate_*.py", True),
    ("tools/migrate_001.py", "migrate_*.py", True),
    ("static/css/app.css", "**/*secret*", False),
])
def test_glob_semantics(path: str, glob: str, expected: bool):
    assert globs.match(path, glob) is expected


def test_a_root_level_secrets_file_is_never_fast(project: Path):
    lane, _ = chief.decide_lane({**STYLE, "files": ["secrets.py"]}, constitution.resolve(project))

    assert lane == "full"


# --- I7 ----------------------------------------------------------------------

def test_an_interrupt_ends_the_whole_process_tree(monkeypatch):
    killed = []
    monkeypatch.setattr(inference, "_kill_tree", lambda process: killed.append(process))

    class Popen:
        pid = 1
        returncode = None

        def __init__(self, *args, **kwargs):
            pass

        def communicate(self, *args, **kwargs):
            raise KeyboardInterrupt

    monkeypatch.setattr(inference.subprocess, "Popen", Popen)

    with pytest.raises(KeyboardInterrupt):
        inference._run_bounded(["claude"], input="", encoding="utf-8", errors="replace",
                               cwd=".", timeout=5, env=None)
    assert killed, "the interrupted dispatch was left running"


def test_ctrl_c_is_a_message_not_a_traceback(monkeypatch):
    def interrupted(args, prompter):
        raise KeyboardInterrupt
    monkeypatch.setattr(cli, "_handler", lambda args: interrupted)
    prompter = ScriptedPrompter({})

    assert cli.main(["doctor"], prompter) == 130
    assert "Stopped" in prompter.said[-1]


# --- I9 ----------------------------------------------------------------------

def test_the_command_line_carries_one_line_whatever_the_brief(tmp_home: Path):
    """A `claude.cmd` launcher runs through cmd.exe, which keeps only the first line."""
    ruleset = {**config.load_hub_config(),
               "slices": {"conventions": {"text": "rule one\nrule two"}}}
    dispatch = inference.Dispatch(role="implementer", prompt="Do it.",
                                  config=config.load_hub_config(), ruleset=ruleset,
                                  system="Extra\ncontext")

    argv, _ = inference._build(dispatch, "claude")
    prompt = inference._prompt(dispatch)

    assert all("\n" not in arg for arg in argv), "a multi-line argument would be truncated"
    assert argv[argv.index("--append-system-prompt") + 1].startswith("ROLE: implementer")
    for part in (roles.definition("implementer").splitlines()[2], "Extra", "rule two", "Do it."):
        assert part in prompt
