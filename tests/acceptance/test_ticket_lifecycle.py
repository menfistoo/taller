"""Phase D's proof: a queue becomes tickets, one walks to close, a killed one resumes.

Criterion 4 (the phase D part: `ticket new --from-queue` converts answer ⑫) and
criterion 11 / G5 (any ticket resumable from disk after a killed session), run
through the real commands on an empty HOME, then `doctor` with the phase D check
passing rather than skipped.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml

from taller import cli, discovery, doctor, paths, tickets
from taller.commands import brand as brand_command
from taller.prompter import ScriptedPrompter

FIRST_VERSION = ["List the tools", "Record a loan", "Show who has what"]
NEW_PROJECT = {
    "setup.billing": "", "setup.host": "", "setup.language.code": "en",
    "setup.language.ui": "es", "setup.language.commits": "en",
    "q1": "Tracks which neighbour has borrowed which tool.", "q2": "A marketplace.",
    "q3": "Who has which tool.", "q4": "1", "q5": "", "q6": "", "q7": "Tools and loans.",
    "q8": "n", "q9": "1", "q10": "1", "q11": "", "q12": FIRST_VERSION, "brief": "1",
}


def run(argv: list[str], answers: dict | None = None) -> ScriptedPrompter:
    prompter = ScriptedPrompter(answers or {})
    code = cli.main(argv, prompter)
    assert code == 0, "\n".join(prompter.said)
    prompter.assert_all_used()
    return prompter


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def test_a_queue_becomes_tickets_one_closes_and_a_killed_one_resumes(
    tmp_home: Path, stub_claude, identity, monkeypatch,
):
    monkeypatch.setattr(brand_command, "open_in_browser", lambda page: None)
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    projects = paths.home() / "projects"
    run(["project", "new", "toolshed", "--path", str(projects), "--no-open"], NEW_PROJECT)
    project = projects / "toolshed"
    at = ["--path", str(project)]

    # Criterion 4, phase D: answer 12 becomes tickets and the queue empties.
    run(["ticket", "new", "--from-queue", *at])
    assert [t["title"] for t in tickets.list_tickets(project)[0]] == FIRST_VERSION
    assert yaml.safe_load(tickets.read_main(project, ".taller/queue.yml"))["proposed"] == []

    # Ticket 1 walks the fast lane from intake to close.
    run(["ticket", "transition", "1", *at])
    run(["ticket", "transition", "1", "--lane", "fast", *at])
    one = tickets.load(project, 1)
    tree = paths.ticket_worktree("toolshed", 1)
    (tree / "tools.txt").write_text("hammer\n", encoding="utf-8")
    git(tree, "add", "tools.txt")
    git(tree, "commit", "--quiet", "-m", "feat(tools): list the tools")
    for _ in range(3):
        run(["ticket", "transition", "1", *at])
    run(["ticket", "approve", "1", *at])                   # review
    git(project, "merge", "--quiet", "--no-edit", one["branch"])
    run(["ticket", "transition", "1", *at])                # pr -> merge
    run(["ticket", "transition", "1", *at])                # merge -> release
    run(["ticket", "approve", "1", *at])                   # release -> close
    one = tickets.load(project, 1)
    assert (one["stage"], one["outcome"]) == ("close", "done")
    assert (project / "tools.txt").read_text(encoding="utf-8") == "hammer\n"

    # Ticket 2 is at build when its session dies and takes the worktree with it.
    run(["ticket", "transition", "2", *at])
    run(["ticket", "transition", "2", "--lane", "full", *at])
    run(["ticket", "approve", "2", *at])                   # design -> build
    two = tickets.load(project, 2)
    shutil.rmtree(paths.ticket_worktree("toolshed", 2))
    said = "\n".join(run(["ticket", "resume", "2", *at]).said)
    assert "worktree recreated" in said.lower()
    assert tickets.load(project, 2)["stage"] == "build"

    # Doctor: green, with the phase D check passing rather than skipped.
    assert cli.main(["doctor"], ScriptedPrompter({})) == 0
    checks = {c.name: c for c in doctor.run_checks()}
    assert checks["toolshed: tickets readable; none left unpushed"].status == doctor.PASS
    assert not [c for c in checks.values() if c.status == doctor.SKIP and c.phase == "D"]
