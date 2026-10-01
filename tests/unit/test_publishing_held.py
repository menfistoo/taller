"""Nothing leaves her machine until she says so.

Before this, every write to `main` pushed it whenever the project had a remote
(spec 7.3), and every new ticket opened a GitHub issue carrying her words. Both
are publishing. Now both wait for `publish.automatic`, which is off, and one call
- `taller publish`, or the button - sends everything that waited.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import support
from taller import cli, discovery, doctor, gitio, issues, publishing, settings, tickets
from taller.prompter import ScriptedPrompter


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A real bare repository standing in for GitHub: pushes land, nothing leaves."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(bare)], check=True)
    return bare


@pytest.fixture
def gh(monkeypatch) -> list[list[str]]:
    """Every `gh` call, answered as if GitHub had opened issue #11."""
    calls: list[list[str]] = []

    def fake(args, **kwargs):
        calls.append(list(args))
        if args[:2] == ["issue", "create"]:
            return subprocess.CompletedProcess(args, 0, "https://github.com/x/y/issues/11\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(discovery, "_run_gh", fake)
    monkeypatch.setattr(issues, "repo_of", lambda project: "someone/toolshed")
    return calls


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, remote, gh) -> Path:
    return support.new_project(origin=str(remote))


def remote_main(remote: Path) -> str | None:
    done = subprocess.run(["git", "--git-dir", str(remote), "rev-parse", "--verify", "--quiet",
                           "refs/heads/main"], capture_output=True, text=True)
    return done.stdout.strip() or None


def issues_opened(gh: list[list[str]]) -> int:
    return sum(1 for call in gh if call[:2] == ["issue", "create"])


def test_by_default_nothing_is_pushed(project, remote):
    tickets.create(project, title="A thing", words="Do it.", kind="bug")

    assert remote_main(remote) is None, "main reached the remote without being asked"
    assert tickets.load(project, 1)["sync"] == publishing.HELD


def test_by_default_no_issue_is_opened(project, gh):
    tickets.create(project, title="A thing", words="Do it.", kind="bug")
    tickets.write(project, tickets.load(project, 1), "ticket 0001: again")

    assert issues_opened(gh) == 0, "her words went to GitHub without being asked"
    assert tickets.load(project, 1)["issue"] is None


def test_what_is_waiting_is_said(project):
    tickets.create(project, title="A thing", words="Do it.", kind="bug")

    waiting = publishing.waiting(project)

    assert waiting["held"] is True and waiting["remote"]
    assert waiting["commits"], "nothing listed as waiting"
    assert all(set(commit) == {"sha", "subject"} for commit in waiting["commits"])
    assert waiting["tickets_without_issue"] == [1]


def test_publishing_sends_everything_that_was_held(project, remote):
    tickets.create(project, title="A thing", words="Do it.", kind="bug")

    sent = publishing.send(project)

    assert sent["problem"] == "" and sent["sent"] >= 1
    assert remote_main(remote) == gitio.git(project, "rev-parse", "main").stdout.strip()
    assert tickets.effective_sync(project, tickets.load(project, 1)) == gitio.SYNC_OK
    assert publishing.waiting(project)["held"] is False


def test_publishing_opens_the_issues_that_were_held_back(project, gh, remote):
    tickets.create(project, title="A thing", words="Do it.", kind="bug")

    publishing.send(project)

    assert issues_opened(gh) == 1
    assert tickets.load(project, 1)["issue"] == 11
    # The number is recorded, and the record itself went out with the push.
    assert remote_main(remote) == gitio.git(project, "rev-parse", "main").stdout.strip()


def test_a_project_with_no_remote_has_nothing_to_publish(tmp_home, identity, stub_claude, gh):
    alone = support.new_project("boathouse")
    tickets.create(alone, title="A thing", words="Do it.", kind="bug")

    waiting = publishing.waiting(alone)
    sent = publishing.send(alone)

    assert waiting["remote"] == "" and waiting["held"] is False
    assert waiting["reason"] == "this project is only on this computer"
    assert sent == {"sent": 0, "remote": "", "problem": ""}
    assert tickets.load(alone, 1)["sync"] == gitio.SYNC_LOCAL


def test_a_refused_push_says_so_and_changes_nothing(tmp_home, identity, stub_claude, gh,
                                                   tmp_path):
    unreachable = support.new_project(origin=str(tmp_path / "no-such-remote.git"))
    tickets.create(unreachable, title="A thing", words="Do it.", kind="bug")

    sent = publishing.send(unreachable)

    assert sent["problem"] and sent["sent"] == 0
    assert "Traceback" not in sent["problem"]
    assert publishing.waiting(unreachable)["held"] is True, "held work was lost"


def test_turning_it_on_restores_the_old_behaviour(project, remote, gh):
    settings.set_value("publish.automatic", "true")

    tickets.create(project, title="Another", words="Do it.", kind="bug")

    assert remote_main(remote) is not None
    assert tickets.load(project, 1)["sync"] == gitio.SYNC_OK
    assert issues_opened(gh) == 1


def test_it_is_off_unless_someone_turns_it_on(project):
    assert publishing.automatic(project) is False
    settings.set_value("publish.automatic", "true", project)
    assert publishing.automatic(project) is True


def test_doctor_does_not_call_held_work_a_fault(project):
    tickets.create(project, title="A thing", words="Do it.", kind="bug")

    rows = [check for check in doctor.run_checks() if "unpushed" in check.name
            or "published" in check.name]

    assert rows and all(check.status != doctor.FAIL for check in rows)


def test_taller_publish_says_what_it_sent(project, remote):
    tickets.create(project, title="A thing", words="Do it.", kind="bug")
    prompter = ScriptedPrompter({})

    code = cli.main(["publish", "--path", str(project)], prompter)

    said = "\n".join(prompter.said)
    assert code == 0 and "sent" in said.lower()
    assert remote_main(remote) is not None
