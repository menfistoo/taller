"""tickets.py — the ticket on disk: schema, reads from `main`, create, notes, sync.

Spec 7.1 and 7.2. A ticket lives on `main` and is read from `main`: the owner's
checkout may be sitting on a ticket branch, where `.taller/work/` is whatever it
was when the branch was cut.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest
import yaml

import support
from taller import gitio, tickets
from taller.errors import ConfigError

WORDS = "The mismatch warning uses a different red\n\n> from the rest of the app.  \n"


@pytest.fixture
def project(tmp_home: Path, identity) -> Path:
    return support.new_project()


def git(project: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout


def status_on_main(project: Path, ticket: dict) -> dict:
    return yaml.safe_load(tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/status.yml"))


def test_create_writes_three_files_on_main_and_numbers_from_one(project: Path):
    ticket = tickets.create(project, title="Danger colour mismatch", words=WORDS, kind="bug")

    assert ticket["id"] == 1
    assert tickets.ticket_dir(ticket) == ".taller/work/0001-danger-colour-mismatch"
    for name in ("ticket.md", "status.yml", "notes.md"):
        assert tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/{name}"), name
    status = status_on_main(project, ticket)
    assert (status["stage"], status["lane"], status["kind"]) == ("intake", None, "bug")
    assert status["checkpoints"] == {"design": "pending", "review": "pending",
                                     "staging": "pending", "release": "pending"}
    assert status["blocked"] is None and status["branch"] is None
    notes = tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/notes.md").decode()
    assert "created at ① intake" in notes


def test_the_owners_words_are_kept_verbatim(project: Path):
    ticket = tickets.create(project, title="Words", words=WORDS, kind="idea")

    body = tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/ticket.md").decode()
    assert WORDS in body


def test_reads_come_from_main_even_on_a_branch(project: Path):
    tickets.create(project, title="First", words="one", kind="idea")
    git(project, "checkout", "--quiet", "-b", "other")

    second = tickets.create(project, title="Second", words="two", kind="idea")

    assert second["id"] == 2
    found, problems = tickets.list_tickets(project)
    assert [t["id"] for t in found] == [1, 2] and problems == []
    assert git(project, "status", "--porcelain") == ""
    assert not (project / tickets.ticket_dir(second)).exists(), (
        "ticket 2 was written into the owner's branch")


def test_ids_do_not_collide_across_threads(project: Path):
    """Two writers at once: each gets a distinct id, or - past the 5s the spec
    allows (10.3) - a clear LockTimeout. Never the same id twice."""
    from taller.errors import LockTimeout

    unexpected: list[BaseException] = []
    made: list[int] = []

    def make(prefix: str):
        for n in range(3):
            try:
                made.append(tickets.create(project, title=f"{prefix} {n}", words="w",
                                           kind="idea")["id"])
            except LockTimeout:
                pass
            except BaseException as exc:              # surfaced below
                unexpected.append(exc)

    threads = [threading.Thread(target=make, args=(p,)) for p in ("left", "right")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert unexpected == []
    assert len(made) == len(set(made)) >= 3
    on_main = sorted(t["id"] for t in tickets.list_tickets(project)[0])
    assert on_main == sorted(made) == list(range(1, len(made) + 1))


@pytest.mark.parametrize("title, slug", [
    ("Arreglar el botón", "arreglar-el-boton"),
    ("¿Qué pasa?", "que-pasa"),
    ("🙂🙂", "ticket"),
    ("!!!", "ticket"),
])
def test_slugify(title: str, slug: str):
    assert tickets.slugify(title) == slug


def test_a_long_title_slugs_to_forty_characters_without_a_trailing_hyphen():
    slug = tickets.slugify("a b " * 200)

    assert len(slug) <= 40 and not slug.endswith("-")


def test_a_broken_status_is_named_not_raised_from_list(project: Path):
    first = tickets.create(project, title="First", words="one", kind="idea")
    tickets.create(project, title="Second", words="two", kind="idea")
    broken = f"{tickets.ticket_dir(first)}/status.yml"
    gitio.commit_to_main(project, {broken: b"stage: [unclosed\n"}, "break it")

    found, problems = tickets.list_tickets(project)

    assert [t["id"] for t in found] == [2]
    assert len(problems) == 1 and "0001" in problems[0]
    with pytest.raises(ConfigError, match="0001-first/status.yml"):
        tickets.load(project, 1)


def test_sync_is_local_without_a_remote(project: Path):
    ticket = tickets.create(project, title="Local", words="w", kind="idea")

    assert status_on_main(project, ticket)["sync"] == "local"


def test_sync_is_pending_when_the_push_fails(tmp_home: Path, identity):
    project = support.new_project(origin=str(tmp_home / "no-such-remote.git"))

    ticket = tickets.create(project, title="Unpushed", words="w", kind="idea")

    assert status_on_main(project, ticket)["sync"] == "pending"
    assert ticket["sync"] == "pending"


def test_queue_yml_may_be_written_to_main(project: Path):
    gitio.commit_to_main(project, {".taller/queue.yml": b"proposed: []\n"}, "empty the queue")

    assert tickets.read_main(project, ".taller/queue.yml") == b"proposed: []\n"
