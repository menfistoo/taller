"""Publishing, from the front page: one line and one button per project.

Nothing leaves her computer until she presses it (Task 1). The front page says,
per project, whether anything is waiting - and a project with nowhere to publish
to says so instead of offering a button that could only fail.
"""

from __future__ import annotations

import html
import re
import subprocess
from pathlib import Path

import pytest

import support
import cockpit
from taller import discovery, gitio, issues, publishing, tickets


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(bare)], check=True)
    return bare


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch, remote) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    monkeypatch.setattr(issues, "repo_of", lambda project: None)   # a remote, not GitHub
    return support.new_project(origin=str(remote))


@pytest.fixture
def client(project):
    return cockpit.create_app(testing=True).test_client()


def text_of(answer) -> str:
    page = answer.get_data(as_text=True)
    page = re.sub(r"(?s)<(style|script)\b.*?</\1>", " ", page)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def remote_main(remote: Path) -> str | None:
    done = subprocess.run(["git", "--git-dir", str(remote), "rev-parse", "--verify", "--quiet",
                           "refs/heads/main"], capture_output=True, text=True)
    return done.stdout.strip() or None


def test_the_page_says_what_has_not_left_this_computer(project, client):
    tickets.create(project, title="A thing", words="Do it.", kind="bug")
    tickets.create(project, title="Another", words="Do it too.", kind="bug")

    page = text_of(client.get("/"))

    assert "2 things have not left this computer yet." in page
    assert "Publish" in page


def test_pressing_publish_sends_it(project, client, remote):
    tickets.create(project, title="A thing", words="Do it.", kind="bug")

    answer = client.post("/publish/toolshed", data=token(client), follow_redirects=True)

    assert remote_main(remote) == gitio.git(project, "rev-parse", "main").stdout.strip()
    page = text_of(answer)
    assert "Published" in page
    assert "have not left this computer" not in page


def test_a_project_with_no_remote_offers_no_button(tmp_home, identity, stub_claude, monkeypatch):
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    alone = support.new_project("boathouse")
    tickets.create(alone, title="A thing", words="Do it.", kind="bug")
    client = cockpit.create_app(testing=True).test_client()

    raw = client.get("/").get_data(as_text=True)
    page = text_of(client.get("/"))

    assert "only on this computer" in page
    assert "/publish/boathouse" not in raw


def test_a_refused_push_is_one_sentence_and_nothing_is_lost(tmp_home, identity, stub_claude,
                                                           monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    monkeypatch.setattr(issues, "repo_of", lambda project: None)
    unreachable = support.new_project(origin=str(tmp_path / "gone.git"))
    tickets.create(unreachable, title="A thing", words="Do it.", kind="bug")
    client = cockpit.create_app(testing=True).test_client()

    answer = client.post("/publish/toolshed", data=token(client), follow_redirects=True)

    page = text_of(answer)
    assert "could not be reached" in page and "Traceback" not in page
    assert publishing.waiting(unreachable)["held"] is True


def test_publishing_needs_the_token(project, client, remote):
    tickets.create(project, title="A thing", words="Do it.", kind="bug")

    answer = client.post("/publish/toolshed", data={})

    assert answer.status_code == 400 and remote_main(remote) is None


def test_the_front_page_reads_each_project_s_tickets_once(project, client, monkeypatch):
    """Publishing's check is on the front page for every project now; it must not
    read every ticket again (part two's review found that class of slowness)."""
    for number in range(6):
        tickets.create(project, title=f"Thing {number}", words="Do it.", kind="bug")
    reads: list[int] = []
    real = tickets.list_tickets
    monkeypatch.setattr(tickets, "list_tickets", lambda path: reads.append(1) or real(path))

    client.get("/")

    assert len(reads) == 1, f"the tickets were read {len(reads)} times"
