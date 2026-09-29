"""Phase B's proof: one ticket, stated once, carried from intake to close.

Criterion 4 (B part) - a ticket runs ① → ⑩ end to end; criterion 12 - it
records weighted spend by reported model; criterion 13 - it never passes ⑦ or
⑪ without the owner's approval. On an empty HOME, through the real commands,
with the stub `claude` answering each role from a script.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from taller import cli, discovery, doctor, paths, tickets
from taller.commands import brand as brand_command
from taller.prompter import ScriptedPrompter

NEW_PROJECT = {
    "setup.billing": "", "setup.host": "", "setup.language.code": "en",
    "setup.language.ui": "es", "setup.language.commits": "en",
    "q1": "Tracks which neighbour has borrowed which tool.", "q2": "A marketplace.",
    "q3": "Who has which tool.", "q4": "1", "q5": "", "q6": "", "q7": "Tools and loans.",
    "q8": "n", "q9": "1", "q10": "1", "q11": "", "q12": ["List the tools"], "brief": "1",
}
SCRIPT = {
    "chief": [{"value": {"kind": "bug", "title": "Heading uses the danger colour",
                         "summary": "The page heading should use the danger token."}}],
    "explorer": [{"value": {"files": ["static/css/app.css"], "adds_or_deletes_files": False,
                            "schema_change": False, "route_change": False,
                            "dependency_change": False, "change_kind": "style",
                            "notes": "One rule in app.css."}}],
    "implementer": [{"value": {"summary": "The heading now uses --color-danger.",
                               "commits": []},
                     "effects": [{"write": "static/css/app.css",
                                  "text": "h1 { color: var(--color-danger, inherit); }\n"},
                                 {"commit": "fix(ui): heading uses the danger token"}]}],
    "summariser": [{"value": {"summary_md": "One rule in static/css/app.css changed."}}],
}


def run(argv: list[str], answers: dict | None = None) -> ScriptedPrompter:
    prompter = ScriptedPrompter(answers or {})
    code = cli.main(argv, prompter)
    assert code == 0, "\n".join(prompter.said)
    prompter.assert_all_used()
    return prompter


def test_one_ticket_stated_once_runs_from_intake_to_close(
    tmp_home: Path, tmp_path: Path, stub_claude, identity, monkeypatch,
):
    monkeypatch.setattr(brand_command, "open_in_browser", lambda page: None)
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    projects = paths.home() / "projects"
    run(["project", "new", "toolshed", "--path", str(projects), "--no-open"], NEW_PROJECT)
    project = projects / "toolshed"
    at = ["--path", str(project)]
    run(["models", "probe"])

    script = tmp_path / "script.json"
    script.write_text(json.dumps(SCRIPT), encoding="utf-8")
    monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(script))

    # G2: the owner states intent once.
    run(["ticket", "new", "The", "heading", "should", "be", "the", "danger", "red", *at])
    assert tickets.load(project, 1)["kind"] == "bug"

    # Carried to the review checkpoint, and no further (criterion 13).
    run(["ticket", "run", "1", *at])
    ticket = tickets.load(project, 1)
    assert (ticket["stage"], ticket["lane"]) == ("review", "fast")
    assert ticket["checkpoints"]["review"] == "pending"

    run(["ticket", "approve", "1", *at])
    said = "\n".join(run(["ticket", "run", "1", *at]).said)
    assert tickets.load(project, 1)["stage"] == "pr" and "merge" in said

    subprocess.run(["git", "-C", str(project), "merge", "--quiet", "--no-edit",
                    ticket["branch"]], check=True, capture_output=True)
    run(["ticket", "run", "1", *at])
    assert tickets.load(project, 1)["stage"] == "release"        # waits for ⑪

    run(["ticket", "approve", "1", *at])
    ticket = tickets.load(project, 1)
    assert (ticket["stage"], ticket["outcome"]) == ("close", "done")

    # Criterion 12: weighted spend, by the model the run reported.
    assert ticket["spend"]["weighted_tokens"] > 0
    assert set(ticket["spend"]["by_model"]) == {"claude-sonnet-5"}
    notes = tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/notes.md").decode()
    assert notes.index("review approved by the owner") < notes.index("⑦ review → ⑧ pr")
    assert notes.index("release approved by the owner") < notes.index("⑪ release → ⑫ close")

    # Doctor, with phase B's rows passing.
    monkeypatch.delenv("STUB_CLAUDE_SCRIPT")
    assert cli.main(["doctor"], ScriptedPrompter({})) == 0
    checks = {c.name: c for c in doctor.run_checks()}
    assert checks["every configured model reachable (last `taller models probe`)"].status \
        == doctor.PASS
    assert checks["billing mode matches the environment; pricing not stale"].status \
        == doctor.PASS
