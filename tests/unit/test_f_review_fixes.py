"""What the whole-branch review of phase F found, each pinned by a test.

The worst of them: the file added to prove this repository names nobody was the
only tracked file naming its owner. The rest are the two features she would
actually have used - the pull request and doctor's "is it safe on GitHub?" -
failing in the ordinary case.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

import support
from taller import (cli, discovery, doctor, generated, github, gitio, paths, prs, scaffold,
                    tickets)
from taller.commands import stage as stage_command
from taller.prompter import ScriptedPrompter

REPO = "someone/toolshed"
WORKFLOW = ".github/workflows/taller-ci.yml"


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    return support.new_project()


# --- C1: no tracked file names her, including the test that checks it ------------------

def test_no_tracked_file_names_the_owner():
    """Her own words come from her hub; this repository holds none of them.

    Deliberately not `tmp_home`: on her machine the hub list is read, so the scan
    covers her real words. Elsewhere - a fresh clone, CI - there is no hub and the
    made-up list is all there is to check.
    """
    found = support.scan_tracked_files(support.vocabulary_words())

    assert found == []


def test_the_test_that_checks_it_is_not_exempt():
    assert "tests/unit/test_publishing.py" not in support.VOCABULARY_EXEMPT


# --- C3: the branch is pushed before a pull request is asked for ----------------------

def test_a_pull_request_pushes_the_branch_first(project, monkeypatch):
    remote = project.parent / "toolshed-remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
    support.git(project, "remote", "add", "origin", str(remote))
    ticket = tickets.create(project, title="Ledger", words="Add a ledger.", kind="feature")
    ticket.update({"branch": "ticket/0001-ledger", "stage": "pr"})
    tickets.write(project, ticket, "ticket 0001: at pr")
    support.git(project, "branch", ticket["branch"], "main")
    monkeypatch.setattr("taller.issues.repo_of", lambda path: REPO)
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: subprocess.CompletedProcess(
        args, 0, "https://github.com/someone/toolshed/pull/4\n", ""))

    number, reason = prs.create(project, tickets.load(project, ticket["id"]))

    assert (number, reason) == (4, "")
    assert ticket["branch"] in support.git(remote, "branch", "--list", ticket["branch"])


def test_a_push_that_fails_is_the_reason(project, monkeypatch):
    support.git(project, "remote", "add", "origin", str(project.parent / "nowhere.git"))
    ticket = tickets.create(project, title="Ledger", words="x", kind="feature")
    ticket.update({"branch": "ticket/0001-ledger", "stage": "pr"})
    tickets.write(project, ticket, "ticket 0001: at pr")
    support.git(project, "branch", ticket["branch"], "main")
    monkeypatch.setattr("taller.issues.repo_of", lambda path: REPO)

    number, reason = prs.create(project, tickets.load(project, ticket["id"]))

    assert number is None and "push" in reason.lower()


# --- I4, I5: the body travels on stdin; an existing pull request is adopted ------------

def test_the_body_goes_on_stdin_not_the_command_line(project, monkeypatch):
    calls: list[tuple[list[str], str | None]] = []

    def fake(args, input=None):
        calls.append((args, input))
        return subprocess.CompletedProcess(args, 0, "https://x/pull/9\n", "")
    monkeypatch.setattr("taller.issues.repo_of", lambda path: REPO)
    monkeypatch.setattr(prs, "_push_branch", lambda project, branch: None)
    monkeypatch.setattr(discovery, "_run_gh", fake)
    ticket = tickets.create(project, title="Ledger", words="x" * 40_000, kind="feature")
    ticket.update({"branch": "ticket/0001-ledger", "stage": "pr"})
    tickets.write(project, ticket, "ticket 0001: at pr")

    prs.create(project, tickets.load(project, ticket["id"]))

    created = [(a, i) for a, i in calls if a[:2] == ["pr", "create"]][0]
    assert "--body-file" in created[0] and "-" in created[0]
    assert "--body" not in created[0]
    assert created[1] and "x" * 100 in created[1]


def test_an_existing_pull_request_is_adopted_not_duplicated(project, monkeypatch):
    seen: list[list[str]] = []

    def fake(args, input=None):
        seen.append(args)
        if args[:2] == ["pr", "list"]:
            return subprocess.CompletedProcess(args, 0, json.dumps(
                [{"number": 6, "state": "OPEN"}]), "")
        return subprocess.CompletedProcess(args, 0, "https://x/pull/7\n", "")
    monkeypatch.setattr("taller.issues.repo_of", lambda path: REPO)
    monkeypatch.setattr(prs, "_push_branch", lambda project, branch: None)
    monkeypatch.setattr(discovery, "_run_gh", fake)
    ticket = tickets.create(project, title="Ledger", words="x", kind="feature")
    ticket.update({"branch": "ticket/0001-ledger", "stage": "pr"})
    tickets.write(project, ticket, "ticket 0001: at pr")

    assert prs.create(project, tickets.load(project, ticket["id"])) == (6, "")
    assert not [args for args in seen if args[:2] == ["pr", "create"]]


# --- C5: a rejected ticket forgets its pull request ------------------------------------

def test_rejecting_at_review_forgets_the_pull_request(project):
    ticket = tickets.create(project, title="Ledger", words="x", kind="bug")
    ticket.update({"stage": "review", "pr": 12, "branch": None})
    ticket["checkpoints"]["review"] = "pending"
    tickets.write(project, ticket, "ticket 0001: at review")

    rejected = tickets.reject(project, ticket["id"], "Use the brand's own red")

    assert rejected["pr"] is None


# --- C4, I2, I3: what GitHub says about the last real change ---------------------------

def merge_on_main(project: Path) -> str:
    """A merge commit on main, as GitHub's merge button makes."""
    support.git(project, "checkout", "-q", "-b", "side")
    support.write(project / "static" / "css" / "app.css", "h1 { color: inherit; }\n")
    support.git(project, "add", "--all")
    support.git(project, "commit", "-q", "-m", "fix(ui): the heading")
    support.git(project, "checkout", "-q", "main")
    support.git(project, "merge", "--no-ff", "-q", "side", "-m", "Merge branch 'side'")
    return support.git(project, "rev-parse", "HEAD").strip()


def gh_runs(entries: list[dict], checks: list[dict] | None = None):
    def fake(args, input=None):
        joined = " ".join(args)
        if "run list" in joined:
            return subprocess.CompletedProcess(args, 0, json.dumps(entries), "")
        if "check-runs" in joined:
            return subprocess.CompletedProcess(args, 0, json.dumps(
                {"check_runs": checks or []}), "")
        return subprocess.CompletedProcess(args, 1, "", "not stood in for")
    return fake


def test_a_merge_commit_is_a_real_change(project, monkeypatch):
    sha = merge_on_main(project)
    monkeypatch.setattr(discovery, "_run_gh", gh_runs(
        [{"conclusion": "failure", "status": "completed", "headSha": sha}],
        [{"name": "taller-ci", "conclusion": "failure", "status": "completed"}]))

    assert github.latest_ci(project, REPO)["state"] == "failed"


def test_a_run_still_going_is_not_called_failed(project, monkeypatch):
    sha = merge_on_main(project)
    monkeypatch.setattr(discovery, "_run_gh", gh_runs(
        [{"conclusion": "", "status": "in_progress", "headSha": sha}]))

    found = github.latest_ci(project, REPO)

    assert found["state"] == "unknown" and "still running" in found["detail"]


def test_the_required_check_decides_not_the_whole_run(project, monkeypatch):
    sha = merge_on_main(project)
    monkeypatch.setattr(discovery, "_run_gh", gh_runs(
        [{"conclusion": "failure", "status": "completed", "headSha": sha}],
        [{"name": "taller-ci", "conclusion": "success", "status": "completed"},
         {"name": "taller-ci-mode", "conclusion": "failure", "status": "completed"}]))

    assert github.latest_ci(project, REPO)["state"] == "green"


# --- I1: "could not ask GitHub" is not "not protected" --------------------------------

def test_gh_missing_leaves_protection_unknown(project, monkeypatch):
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)

    assert github.protection(REPO)["ok"] is None


def test_doctor_skips_rather_than_fails_when_github_cannot_be_asked(project, monkeypatch):
    monkeypatch.setattr("taller.issues.repo_of", lambda path: REPO)
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)

    # The two rows that ask GitHub. The third F row - whether CI could install
    # Taller at all - is answered from her own settings and is not affected.
    rows = [c for c in doctor.run_checks()
            if c.phase == "F" and "install Taller" not in c.name]

    assert [c.status for c in rows] == [doctor.SKIP, doctor.SKIP]


# --- C6: a base that compares nothing is refused -------------------------------------

def test_a_base_equal_to_the_head_is_refused(project, capsys):
    code = cli.main(["ci", "--path", str(project), "--base", "HEAD"])

    out = capsys.readouterr().out
    assert code == 2 and "nothing to compare" in out.lower()


def test_the_workflow_asks_git_to_verify_the_parent():
    text = (paths.catalogue() / "ci" / "taller-ci.yml").read_text(encoding="utf-8")

    assert "rev-parse --verify" in text
    assert "rev-parse HEAD~1 2>/dev/null" not in text


# --- I6: a branch with main merged into it is not "carrying the snapshot" -------------

def test_merging_main_into_a_branch_does_not_look_like_a_carried_snapshot(project, capsys):
    support.git(project, "checkout", "-q", "-b", "work")
    support.write(project / "static" / "css" / "app.css", "h1 { color: inherit; }\n")
    support.git(project, "add", "--all")
    support.git(project, "commit", "-q", "-m", "fix(ui): the heading")
    support.git(project, "checkout", "-q", "main")
    generated.refresh(project)                       # main's snapshot moves on
    support.git(project, "checkout", "-q", "work")
    support.git(project, "merge", "-q", "--no-ff", "main", "-m", "Merge branch 'main'")

    code = cli.main(["ci", "--path", str(project), "--base", "main"])

    assert code == 0, capsys.readouterr().out


def test_a_branch_that_really_edits_the_snapshot_is_still_refused(project, capsys):
    support.git(project, "checkout", "-q", "-b", "work")
    snapshot = project / ".taller" / "resolved.json"
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    data["hub_sha"] = "0" * 40
    support.write(snapshot, json.dumps(data))
    support.git(project, "add", "--all")
    support.git(project, "commit", "-q", "-m", "chore: edit the snapshot")

    code = cli.main(["ci", "--path", str(project), "--base", "main"])

    assert code == 2 and "resolved.json" in capsys.readouterr().out


# --- I7: an unset install address never installs a stranger's package ----------------

def test_an_unset_source_makes_ci_stop_rather_than_install_anything(tmp_home: Path):
    text = scaffold.ci_workflow("").decode("utf-8")

    # Nothing is installed by name: `pip install -r requirements.txt` for the
    # project's own dependencies is fine, `pip install taller` never is.
    assert 'pip install "' not in text and "pip install taller" not in text
    assert "ci.taller_source" in text and "exit 1" in text


def test_a_set_source_installs_exactly_it(tmp_home: Path):
    text = scaffold.ci_workflow("taller @ git+https://example.invalid/t@v1").decode("utf-8")

    assert 'pip install "taller @ git+https://example.invalid/t@v1"' in text


def test_doctor_reports_an_unset_source_for_a_project_on_github(project, monkeypatch):
    monkeypatch.setattr("taller.issues.repo_of", lambda path: REPO)
    monkeypatch.setattr(discovery, "_run_gh", gh_runs([]))

    row = [c for c in doctor.run_checks() if "install Taller" in c.name]

    assert [c.status for c in row] == [doctor.FAIL]
    assert "ci.taller_source" in row[0].fix


# --- I9, I10: staging touches neither production's ports nor her live data ------------

def test_staging_brings_up_only_its_own_compose_file(project):
    from taller import constitution

    ruleset = constitution.resolve(project)

    argv = stage_command.command(project, "toolshed", ruleset)

    assert "docker-compose.yml" not in argv
    assert argv.count("-f") == 1 and "docker-compose.staging.yml" in argv


def test_the_staging_data_folder_is_ignored_by_git(project):
    ignore = (project / ".gitignore").read_text(encoding="utf-8")

    assert "data-staging" in ignore


def test_a_copy_that_git_would_track_is_refused(project, monkeypatch):
    ticket = tickets.create(project, title="Ledger", words="x", kind="feature")
    ticket.update({"branch": "ticket/0001-ledger", "stage": "staging", "lane": "full"})
    tickets.write(project, ticket, "ticket 0001: at staging")
    support.git(project, "branch", ticket["branch"], "main")
    tree = tickets._worktree(project, ticket)
    tree.parent.mkdir(parents=True, exist_ok=True)
    support.git(project, "worktree", "add", "--quiet", str(tree), ticket["branch"])
    support.write(tree / ".gitignore", "venv/\n")          # data-staging no longer ignored
    support.git(tree, "add", "--all")
    support.git(tree, "commit", "-q", "-m", "chore: narrow the ignore list")
    support.write(project / "instance" / "app.db", "live rows")
    monkeypatch.setattr(stage_command, "_docker", lambda: "docker")
    prompter = ScriptedPrompter({})

    code = cli.main(["stage", "1", "--path", str(project)], prompter)

    said = "\n".join(prompter.said)
    assert code == cli.EXIT_REFUSED and "data-staging" in said and "ignore" in said


def test_the_copy_says_it_may_be_behind(project, monkeypatch):
    from taller import constitution

    support.write(project / "instance" / "app.db", "live rows")
    tree = project                                  # any folder will do for the copy
    told = stage_command.prepare_data(project, tree, constitution.resolve(project))

    assert "point-in-time" in told or "may be behind" in told
