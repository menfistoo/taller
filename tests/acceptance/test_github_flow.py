"""Phase F's proof: a project checked on GitHub, staged, and green in doctor.

Criterion 16 (a CI workflow per repository), 17 (a staging environment per
project whose profile defines one), 18 (`taller doctor` green on every
registered project, no check skipped). On an empty HOME, through the real
commands, with `gh` and `docker` stood in for - nothing here reaches the network.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

import support
from taller import cli, discovery, doctor, github, paths, tickets
from taller.commands import brand as brand_command
from taller.commands import stage as stage_command
from taller.prompter import ScriptedPrompter

REPO = "someone/toolshed"
WORKFLOW = ".github/workflows/taller-ci.yml"
NEW_PROJECT = {
    "setup.billing": "", "setup.host": "", "setup.language.code": "en",
    "setup.language.ui": "es", "setup.language.commits": "en",
    "q1": "Tracks which neighbour has borrowed which tool.", "q2": "A marketplace.",
    "q3": "Who has which tool.", "q4": "1", "q5": "", "q6": "", "q7": "Tools and loans.",
    "q8": "n", "q9": "1", "q10": "1", "q11": "", "q12": ["List the tools"], "brief": "1",
}
RULESETS = [{"id": 5, "name": "main", "target": "branch"}]
RULES = {"conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
         "rules": [{"type": "pull_request"},
                   {"type": "required_status_checks",
                    "parameters": {"required_status_checks": [{"context": "taller-ci"}]}}]}


def run(argv: list[str], answers: dict | None = None) -> ScriptedPrompter:
    prompter = ScriptedPrompter(answers or {})
    code = cli.main(argv, prompter)
    assert code == 0, "\n".join(prompter.said)
    prompter.assert_all_used()
    return prompter


def test_a_project_is_checked_on_github_staged_and_green_in_doctor(
    tmp_home: Path, tmp_path: Path, stub_claude, identity, monkeypatch, capsys,
):
    monkeypatch.setattr(brand_command, "open_in_browser", lambda page: None)
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    projects = paths.home() / "projects"
    run(["project", "new", "toolshed", "--path", str(projects), "--no-open"], NEW_PROJECT)
    project = projects / "toolshed"
    at = ["--path", str(project)]

    # Criterion 16: the repository has the workflow, with both check names.
    jobs = yaml.safe_load((project / WORKFLOW).read_text(encoding="utf-8"))["jobs"]
    assert jobs["gates"]["name"] == "taller-ci" and jobs["mode"]["name"] == "taller-ci-mode"

    # Main's tip before any ticket file lands on it: the commit a green run must
    # sit on, because a ticket-file push proves nothing (spec 9.4, 15.4).
    real_change = support.git(project, "rev-parse", "main").strip()

    # The checks pass on the project as created, and need no hub and no key.
    support.git(project, "checkout", "-q", "-b", "work")
    support.write(project / "static" / "css" / "app.css", "h1 { color: inherit; }\n")
    support.git(project, "add", "--all")
    support.git(project, "commit", "-q", "-m", "fix(ui): the heading")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cli.main(["ci", "--base", "main", *at]) == 0, capsys.readouterr().out

    # A rule the gates catch fails it, by rule id, on the changed line.
    support.write(project / "static" / "css" / "app.css", "h1 { color: #dc3545; }\n")
    support.git(project, "add", "--all")
    support.git(project, "commit", "-q", "-m", "fix(ui): a literal red")
    assert cli.main(["ci", "--base", "main", *at]) == 1
    out = capsys.readouterr().out
    assert "brand.hardcoded-color" in out and "::error file=static/css/app.css" in out

    # Criterion 17: staging comes up on a copy, and the live database is untouched.
    support.git(project, "checkout", "-q", "main")
    live = support.write(project / "instance" / "app.db", "live rows")
    before = (live.read_bytes(), live.stat().st_mtime_ns)
    ticket = tickets.create(project, title="Ledger page", words="Add a ledger.", kind="feature")
    ticket.update({"branch": "ticket/0001-ledger-page", "stage": "staging", "lane": "full"})
    tickets.write(project, ticket, "ticket 0001: at staging")
    support.git(project, "branch", ticket["branch"], "main")
    tree = tickets._worktree(project, ticket)
    tree.parent.mkdir(parents=True, exist_ok=True)
    support.git(project, "worktree", "add", "--quiet", str(tree), ticket["branch"])
    composed: list[list[str]] = []
    monkeypatch.setattr(stage_command, "_docker", lambda: "docker")
    monkeypatch.setattr(stage_command, "_compose", lambda argv, cwd: (
        composed.append(list(argv)) or subprocess.CompletedProcess(argv, 0, "up\n", "")))
    monkeypatch.setattr(stage_command, "_answers", lambda url, timeout_s: (200, b"a page"))

    said = "\n".join(run(["stage", "1", *at]).said)

    assert "-p" in composed[0] and "toolshed-staging" in composed[0]
    assert (tree / "data-staging" / "app.db").read_bytes() == b"live rows"
    assert (live.read_bytes(), live.stat().st_mtime_ns) == before
    assert "http://127.0.0.1:8081" in said

    # Criterion 18: doctor green, and no check skipped for this project - which
    # needs a remote, so GitHub is stood in for.
    monkeypatch.setattr("taller.issues.repo_of", lambda path: REPO)
    monkeypatch.setattr(discovery, "_run_gh", _fake_gh(real_change))
    # Criterion 18 now includes it: without an install address the checks could
    # not run on GitHub at all, so doctor says so until she sets one.
    run(["settings", "set", "ci.taller_source", "taller @ git+file:///taller"])
    monkeypatch.delenv("STUB_CLAUDE_SCRIPT", raising=False)

    assert cli.main(["doctor"]) == 0, capsys.readouterr().out
    checks = doctor.run_checks()
    assert [c.name for c in checks if c.status == doctor.FAIL] == []
    mine = [c for c in checks if c.name.startswith("toolshed:")]
    # Nothing skipped but the brand tokens: this project was created with no brand,
    # so there is no token file for the check to compare (spec 7.2).
    assert [c.name for c in mine if c.status == doctor.SKIP] == ["toolshed: brand tokens current"]
    # Three F rows now: the check was green, merging is protected, and CI can
    # install Taller.
    assert [c.status for c in mine if c.phase == "F"] == [doctor.PASS] * 3


def _fake_gh(head: str):
    """`gh` answering about a repository whose last real run on main was green."""
    def fake(args: list[str]):
        joined = " ".join(args)
        if "run list" in joined:
            payload = [{"conclusion": "success", "status": "completed", "headSha": head,
                        "createdAt": "2026-09-29T10:00:00Z"}]
        elif "rulesets/5" in joined:
            payload = RULES
        elif "rulesets" in joined:
            payload = RULESETS
        else:
            return subprocess.CompletedProcess(args, 1, "", "not stood in for")
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
    return fake
