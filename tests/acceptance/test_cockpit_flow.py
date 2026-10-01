"""Phase E's proof: a ticket seen, approved and carried on from the browser (§12).

On an empty HOME, through the real commands and the real gates, then - for every
decision - through the cockpit's own pages and nothing else. The stub `claude`
stands in for what a model would write, and the runner a click starts is recorded
instead of being run: the point here is that the browser decides and the library
writes, not that a second process can be spawned.
"""

from __future__ import annotations

import json
import subprocess
import types
from pathlib import Path

import pytest

import cockpit
from cockpit import runs
from taller import cli, discovery, paths, tickets
from taller.commands import brand as brand_command
from taller.prompter import ScriptedPrompter

NEW_PROJECT = {
    "setup.billing": "", "setup.host": "", "setup.language.code": "en",
    "setup.language.ui": "es", "setup.language.commits": "en",
    "q1": "Tracks which neighbour has borrowed which tool.", "q2": "A marketplace.",
    "q3": "Who has which tool.", "q4": "1", "q5": "", "q6": "", "q7": "Tools and loans.",
    "q8": "n", "q9": "1", "q10": "1", "q11": "", "q12": ["List the tools"], "brief": "1",
}
# `change_kind: other` fails §8.2's last condition, so the lane is full and the
# ticket stops at ③ design with a plan to read - which is what the page must show.
SCRIPT = {
    "chief": [{"value": {"kind": "feature", "title": "The heading needs the danger colour",
                         "summary": "The page heading should use the danger colour."}}],
    "explorer": [{"value": {"files": ["static/css/app.css"], "adds_or_deletes_files": False,
                            "schema_change": False, "route_change": False,
                            "dependency_change": False, "change_kind": "other",
                            "notes": "One rule in app.css.", "templates": {}}}],
    "architect": [{"value": {"plan_md": "1. Give the heading the danger token.\n"}}],
    "implementer": [{"value": {"summary": "The heading is red now.", "commits": []},
                     "effects": [{"write": "static/css/app.css",
                                  "text": "h1 { color: var(--color-danger, inherit); }\n"},
                                 {"commit": "feat(ui): the heading in the danger colour"}]}],
    # The full lane asks the two model-run gates as well (spec 9.7); both are clean.
    "gate_quality": [{"value": {"findings": []}}],
    "gate_ux": [{"value": {"findings": []}}],
    "summariser": [{"value": {"summary_md": "The heading uses the danger token."}}],
}


def cli_run(argv: list[str], answers: dict | None = None) -> ScriptedPrompter:
    prompter = ScriptedPrompter(answers or {})
    code = cli.main(argv, prompter)
    assert code == 0, "\n".join(prompter.said)
    prompter.assert_all_used()
    return prompter


@pytest.fixture
def at_design(tmp_home: Path, tmp_path: Path, stub_claude, identity, monkeypatch) -> Path:
    """A real project with a real ticket the chief has carried to ③ design."""
    monkeypatch.setattr(brand_command, "open_in_browser", lambda page: None)
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    projects = paths.home() / "projects"
    cli_run(["project", "new", "toolshed", "--path", str(projects), "--no-open"], NEW_PROJECT)
    project = projects / "toolshed"
    cli_run(["models", "probe"])

    script = tmp_path / "script.json"
    script.write_text(json.dumps(SCRIPT), encoding="utf-8")
    monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(script))

    cli_run(["ticket", "new", "The", "heading", "should", "be", "the", "danger", "red",
             "--path", str(project)])
    cli_run(["ticket", "run", "1", "--path", str(project)])
    assert tickets.load(project, 1)["stage"] == "design"
    return project


@pytest.fixture
def browser(monkeypatch) -> tuple:
    """The cockpit's test client, and the list of runs a click asked for."""
    asked: list[list[str]] = []

    def fake(command, log):
        asked.append(list(command))
        log.write_text("Carrying the ticket on.\n", encoding="utf-8")
        return types.SimpleNamespace(pid=4242, poll=lambda: None)

    monkeypatch.setattr(runs, "_spawn", fake)
    return cockpit.create_app(testing=True).test_client(), asked


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def decide(client, what: str, form: dict[str, str] | None = None) -> str:
    answer = client.post(f"/ticket/toolshed/1/{what}", data={**token(client), **(form or {})},
                         follow_redirects=True)
    assert answer.status_code == 200
    return answer.get_data(as_text=True)


def head(project: Path) -> str:
    return subprocess.run(["git", "-C", str(project), "rev-parse", "main"],
                          capture_output=True, text=True, check=True).stdout.strip()


def dirty(project: Path) -> str:
    return subprocess.run(["git", "-C", str(project), "status", "--porcelain"],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_a_ticket_is_read_approved_and_carried_on_from_the_browser(at_design, browser):
    project, (client, asked) = at_design, browser
    before = head(project)

    # ① Reading changes nothing: the board and the page are reads (spec 12).
    board = client.get("/board").get_data(as_text=True)
    assert "The heading needs the danger colour" in board
    assert "waiting for you at design" in board
    plan_page = client.get("/ticket/toolshed/1").get_data(as_text=True)
    assert "Give the heading the danger token." in plan_page
    assert head(project) == before and dirty(project) == ""

    # ② She approves the plan here, and the work carries on in its own process.
    decide(client, "approve")
    assert tickets.load(project, 1)["checkpoints"]["design"] == "approved"
    assert asked and asked[-1][-4:] == ["run", "1", "--path", str(project)]

    # That process is stubbed, so the chief is asked for the same work directly.
    cli_run(["ticket", "run", "1", "--path", str(project)])
    ticket = tickets.load(project, 1)
    assert (ticket["stage"], ticket["blocked"]) == ("review", None)
    assert ticket["gates"] == ["constitution", "size", "tests", "quality", "ux", "smoke"]

    # ③ The page carries what she needs to decide: the change and every verdict.
    page = client.get("/ticket/toolshed/1").get_data(as_text=True)
    assert "static/css/app.css" in page
    for gate in ("constitution", "size", "tests", "quality", "ux", "smoke"):
        assert gate in page
    assert "The heading uses the danger token." in page

    # ④ She approves the review, and the board shows where the ticket went.
    decide(client, "approve")
    assert tickets.load(project, 1)["stage"] == "pr"
    assert asked[-1][-4:] == ["run", "1", "--path", str(project)]
    assert tickets._label("pr") in client.get("/board").get_data(as_text=True)

    # Everything the cockpit wrote, the library wrote: the working tree is clean,
    # and the cockpit's own files are the run's output, outside the project.
    assert dirty(project) == ""
    mine = sorted(p.name for p in runs.runs_dir().iterdir())
    assert mine == ["toolshed-0001.json", "toolshed-0001.log"]
    assert runs.runs_dir().is_relative_to(paths.run_dir())


def test_a_rejection_from_the_browser_sends_it_back_with_her_words(at_design, browser,
                                                                   monkeypatch):
    project, (client, asked) = at_design, browser
    decide(client, "approve")
    cli_run(["ticket", "run", "1", "--path", str(project)])
    assert tickets.load(project, 1)["stage"] == "review"

    page = decide(client, "reject", {"reason": "The heading is fine; the buttons are wrong."})

    ticket = tickets.load(project, 1)
    notes = (tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/notes.md")
             or b"").decode("utf-8")
    assert ticket["stage"] == "triage"
    assert ticket["branch"] is None and ticket["checkpoints"]["review"] == "pending"
    assert "the buttons are wrong" in notes
    assert "triage" in page
    assert len(asked) == 1, "a rejection starts nothing"

    # Nothing about the browser's route left the machine in a state doctor dislikes.
    monkeypatch.delenv("STUB_CLAUDE_SCRIPT")
    assert cli.main(["doctor"], ScriptedPrompter({})) == 0
