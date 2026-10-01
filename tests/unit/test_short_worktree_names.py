"""A ticket worktree is named by its project and number, not by its slug.

The chief writes `gates/<gate>.md` under `.taller/work/<NNNN>-<slug>/` inside the
ticket's worktree, with Python. Git is told to allow long paths; Python, on a
Windows without LongPathsEnabled, is not, and fails past 260 characters. A
worktree named `<project>-<NNNN>-<slug>` carried the slug twice, so a long ask
and a long project name broke a run at its gates. A worktree opened under the
old name is still found, and moved to the short one when the chief next works in
it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import support
from taller import chief, discovery, gitio, paths, spend, tickets
from taller.gates import llm

LONGEST = "a" * 63                                   # the longest name a project may have
FORTY = "The heading should be the danger red, like the rest"
GATE_NAMES = ("constitution", "size", "tests", "smoke", *llm.GATES)


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


def test_the_worktree_folder_does_not_repeat_the_slug(tmp_home):
    # Only the names: a project this long cannot even be created under pytest's
    # deep temporary folder.
    ticket = {"id": 1, "slug": tickets.slugify(FORTY)}
    assert len(ticket["slug"]) == tickets.SLUG_MAX

    tree = paths.ticket_worktree(LONGEST, ticket["id"])

    assert tree.name == f"{LONGEST}-0001"
    gate = max(GATE_NAMES, key=len)
    verdict = tree / tickets.ticket_dir(ticket) / "gates" / f"{gate}.md"
    # What the home folder may take before the deepest verdict passes 260
    # characters: room for a long Windows profile, such as one under OneDrive.
    room = 259 - (len(str(verdict)) - len(str(paths.home())))
    assert room >= 80, f"only {room} characters left for the home folder"


@pytest.mark.skipif(sys.platform != "win32", reason="the 260-character limit is Windows'")
def test_a_run_with_a_long_ask_and_project_name_writes_its_verdicts(
        tmp_home, identity, stub_claude, monkeypatch, script):
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    # Long, but short enough that the owner's own checkout fits under pytest's
    # deep temporary folder: it is the worktree this test is about.
    project = support.new_project("the-neighbourhood-tool-library")
    script(explorer=[{"value": {"files": ["static/css/app.css"], "adds_or_deletes_files": False,
                                "schema_change": False, "route_change": False,
                                "dependency_change": False, "change_kind": "style",
                                "notes": "One rule in app.css."}}],
           implementer=[{"value": {"summary": "Used the danger token.", "commits": []},
                         "effects": [{"write": "static/css/app.css",
                                      "text": "h1 { color: var(--color-danger); }\n"},
                                     {"commit": "fix(ui): the heading colour"}]}],
           summariser=[{"value": {"summary_md": "The heading uses the danger token."}}])
    ticket_id = tickets.create(project, title=FORTY, words=FORTY + " of the brand.",
                               kind="bug")["id"]

    ticket = chief.run(project, ticket_id, say=lambda text: None)

    assert ticket["blocked"] is None, ticket["blocked"]
    assert len(ticket["slug"]) == tickets.SLUG_MAX
    assert ticket["gates"] and all(v["result"] == "pass" for v in ticket["verdicts"].values())
    for gate in ticket["gates"]:
        assert tickets.on_branch(project, ticket, f"gates/{gate}.md")


# --- worktrees opened under the old, longer name ------------------------------------

def _open_under_the_old_name(project: Path) -> tuple[dict, Path]:
    ticket = tickets.create(project, title="Heading", words="x", kind="bug")
    branch = f"ticket/{tickets._name(ticket)}"
    gitio.git(project, "branch", branch, gitio.MAIN_BRANCH)
    old = tickets._old_worktree(project, ticket)
    old.parent.mkdir(parents=True, exist_ok=True)
    gitio.git(project, "worktree", "add", "--quiet", str(old), branch)
    (old / "half-done.txt").write_text("not committed yet\n", encoding="utf-8")
    ticket.update(stage="build", lane="full", branch=branch)
    return tickets.write(project, ticket, "ticket 0001: build"), old


def test_a_worktree_under_the_old_name_is_still_found(project):
    ticket, old = _open_under_the_old_name(project)

    assert old.name == f"toolshed-{tickets._name(ticket)}"
    assert tickets._worktree(project, ticket) == old


def test_the_chief_moves_an_old_worktree_to_the_short_name(project):
    ticket, old = _open_under_the_old_name(project)

    tree = chief._worktree(project, ticket["id"])

    assert tree == paths.ticket_worktree("toolshed", 1) and tree.name == "toolshed-0001"
    assert not old.exists()
    assert (tree / "half-done.txt").read_text(encoding="utf-8") == "not committed yet\n"
    assert gitio.git(tree, "symbolic-ref", "--short", "HEAD").stdout.strip() == ticket["branch"]
    assert tickets._worktree(project, ticket) == tree


def test_an_old_worktree_that_cannot_move_is_used_where_it_is(project, monkeypatch):
    ticket, old = _open_under_the_old_name(project)
    real = gitio.git

    def refuse_move(where, *args, **kwargs):
        if args[:2] == ("worktree", "move"):
            return real(where, "worktree", "move", "--no-such-option", check=False)
        return real(where, *args, **kwargs)
    monkeypatch.setattr(gitio, "git", refuse_move)

    assert chief._worktree(project, ticket["id"]) == old


def test_chat_spend_in_an_old_worktree_is_still_counted(project, tmp_path, monkeypatch):
    ticket, _ = _open_under_the_old_name(project)
    # A short stand-in, as in test_transcript_spend: the real folder's transcript
    # path would pass 260 characters under pytest's temporary directory.
    old = Path(r"C:\wt\toolshed-0001-heading")
    monkeypatch.setattr(tickets, "_old_worktree", lambda project, ticket: old)
    folder = tmp_path / spend.transcript_slug(old)
    folder.mkdir()
    (folder / "chat.jsonl").write_text(json.dumps({
        "type": "assistant", "sessionId": "chat", "gitBranch": ticket["branch"],
        "message": {"id": "m1", "model": "claude-opus-5-5", "usage": {
            "input_tokens": 1, "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0, "output_tokens": 7}}}) + "\n", encoding="utf-8")

    found = spend.from_transcripts(project, ticket, root=tmp_path)

    assert found["claude-opus-5-5"]["output"] == 7
