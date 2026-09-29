"""`taller stage <id>`: a full ticket seen running, on its own port, on a copy.

Spec 13.1. Its own compose project name, its own port, `./data-staging/` holding
a copy of the production database - the live file is never opened, and its
`-wal`/`-shm` are never touched. It runs on the deployment host, never in CI,
because GitHub cannot reach a private server.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import support
from taller import cli, constitution, discovery, tickets
from taller.commands import stage
from taller.prompter import ScriptedPrompter

LIVE = "instance/app.db"


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    return support.new_project()


@pytest.fixture
def fake_docker(monkeypatch, tmp_path: Path):
    """A `docker` that records what it was asked to do and answers success."""
    calls: list[list[str]] = []

    def compose(argv, cwd):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "staging started\n", "")
    monkeypatch.setattr(stage, "_docker", lambda: "docker")
    monkeypatch.setattr(stage, "_compose", compose)
    monkeypatch.setattr(stage, "_answers", lambda url, timeout_s: (200, b"a page"))
    return calls


def at_staging(project: Path) -> dict:
    ticket = tickets.create(project, title="Ledger page", words="Add a ledger page.",
                            kind="feature")
    ticket.update({"branch": "ticket/0001-ledger-page", "stage": "staging", "lane": "full"})
    written = tickets.write(project, ticket, "ticket 0001: at staging")
    support.git(project, "branch", written["branch"], "main")
    tree = tickets._worktree(project, written)
    tree.parent.mkdir(parents=True, exist_ok=True)
    support.git(project, "worktree", "add", "--quiet", str(tree), written["branch"])
    return written


def live_database(project: Path) -> dict[str, tuple[bytes, int]]:
    before = {}
    for name in ("app.db", "app.db-wal", "app.db-shm"):
        path = support.write(project / "instance" / name, f"live {name}")
        before[name] = (path.read_bytes(), path.stat().st_mtime_ns)
    return before


def test_the_compose_command_is_the_specs(project):
    ticket = at_staging(project)
    ruleset = constitution.resolve(project)

    argv = stage.command(project, "toolshed", ruleset)

    # The staging file alone: layering production's compose over it would bring
    # its Caddy, and with it host ports 80 and 443.
    assert argv == ["docker", "compose", "-p", "toolshed-staging",
                    "-f", "docker-compose.staging.yml", "up", "-d", "--build"]


def test_the_data_is_a_copy_and_the_live_file_is_untouched(project, fake_docker):
    ticket = at_staging(project)
    before = live_database(project)

    assert cli.main(["stage", "1", "--path", str(project)], ScriptedPrompter({})) == 0

    after = {name: ((project / "instance" / name).read_bytes(),
                    (project / "instance" / name).stat().st_mtime_ns) for name in before}
    assert after == before                                  # the live files, untouched
    copy = tickets._worktree(project, ticket) / "data-staging" / "app.db"
    assert copy.read_bytes() == before["app.db"][0]
    assert not (copy.parent / "app.db-wal").exists()
    assert not (copy.parent / "app.db-shm").exists()


def test_it_runs_in_the_tickets_worktree(project, fake_docker):
    ticket = at_staging(project)
    live_database(project)

    cli.main(["stage", "1", "--path", str(project)], ScriptedPrompter({}))

    assert fake_docker, "docker was never called"
    assert stage.LAST_CWD == str(tickets._worktree(project, ticket))


def test_the_staging_url_is_reported(project, fake_docker):
    at_staging(project)
    live_database(project)
    prompter = ScriptedPrompter({})

    assert cli.main(["stage", "1", "--path", str(project)], prompter) == 0

    said = "\n".join(prompter.said)
    assert "http://127.0.0.1:8081" in said and "copy" in said


def test_a_project_that_has_never_run_stages_on_an_empty_copy(project, fake_docker):
    at_staging(project)
    prompter = ScriptedPrompter({})

    assert cli.main(["stage", "1", "--path", str(project)], prompter) == 0

    assert "no database yet" in "\n".join(prompter.said)


def test_no_docker_is_a_clear_refusal(project, monkeypatch):
    at_staging(project)
    monkeypatch.setattr(stage, "_docker", lambda: None)
    prompter = ScriptedPrompter({})

    code = cli.main(["stage", "1", "--path", str(project)], prompter)

    assert code == cli.EXIT_REFUSED and "Docker" in "\n".join(prompter.said)


def test_a_profile_without_staging_refuses(project, fake_docker, monkeypatch):
    at_staging(project)
    real = constitution.resolve

    def without_staging(path):
        ruleset = real(path)
        ruleset.pop("staging", None)
        return ruleset
    monkeypatch.setattr(constitution, "resolve", without_staging)
    prompter = ScriptedPrompter({})

    code = cli.main(["stage", "1", "--path", str(project)], prompter)

    assert code == cli.EXIT_REFUSED
    assert "no staging" in "\n".join(prompter.said).lower()


def test_a_ticket_not_at_staging_refuses(project, fake_docker):
    ticket = tickets.create(project, title="x", words="x", kind="bug")
    prompter = ScriptedPrompter({})

    code = cli.main(["stage", str(ticket["id"]), "--path", str(project)], prompter)

    assert code == cli.EXIT_REFUSED and "⑨" in "\n".join(prompter.said)


def test_an_app_that_never_answers_is_reported(project, fake_docker, monkeypatch):
    at_staging(project)
    live_database(project)
    monkeypatch.setattr(stage, "_answers", lambda url, timeout_s: (None, b""))
    prompter = ScriptedPrompter({})

    code = cli.main(["stage", "1", "--path", str(project)], prompter)

    said = "\n".join(prompter.said)
    assert code == cli.EXIT_REFUSED and "did not answer" in said
    assert "docker compose -p toolshed-staging" in said       # so she can look herself


def test_the_chief_names_the_command_at_staging(project, script_or_none=None):
    from taller import chief

    ticket = at_staging(project)
    said: list[str] = []

    chief._step(project, tickets.load(project, ticket["id"]), None,
                __import__("taller").config.load_hub_config(), said.append)

    assert "taller stage 1" in "\n".join(said)
