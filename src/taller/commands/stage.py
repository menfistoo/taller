"""`taller stage <ticket>`: the change, running where the owner can look at it.

Spec 13.1. Its own compose project name, its own port, and `./data-staging/`
holding a **copy** of the production database - the live file is opened by
nothing here, and its `-wal`/`-shm` are not copied, the same care §9.6 takes.

It runs on the deployment host, never in CI: GitHub Actions cannot reach a
Tailscale-only private server, so this is a command the owner runs (§13.1). A
self-hosted runner would automate it and is deliberately deferred.
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from .. import constitution, registry, tickets
from ..errors import ConfigError
from ..prompter import Prompter
from .common import project_path

STAGE = "staging"
DATA_DIR = "data-staging"
TIMEOUT_S = 180             # a first `--build` pulls and compiles
LAST_CWD = ""               # where the last compose ran, for the tests to assert


def command(project: Path, name: str, ruleset: Mapping[str, Any],
            executable: str = "docker") -> list[str]:
    """The compose invocation of spec 13.1, exactly. Pure: the caller resolves docker."""
    staging = ruleset.get(STAGE) or {}
    files = [str(f) for f in (staging.get("compose") or [])]
    argv = [executable, "compose", "-p", f"{name}-{STAGE}"]
    for compose in files:
        argv += ["-f", compose]
    return [*argv, "up", "-d", "--build"]


def prepare_data(project: Path, worktree: Path, ruleset: Mapping[str, Any]) -> str:
    """Copy the production database beside the staging compose. Never opens the live file.

    The `-wal` and `-shm` files are deliberately left behind (spec 9.6's care), so
    for a database in WAL mode the copy is a point-in-time one that can be behind
    production. Said plainly, because a missing row is otherwise read as a defect
    in the change.
    """
    folder = worktree / DATA_DIR
    folder.mkdir(parents=True, exist_ok=True)
    source = (ruleset.get("smoke") or {}).get("database")
    if not source:
        return f"no database is configured, so {DATA_DIR}/ is empty"
    live = project / str(source)
    if not live.is_file():
        return f"no database yet at {source}, so {DATA_DIR}/ starts empty"
    shutil.copyfile(live, folder / live.name)
    return (f"a point-in-time copy of {source} in {DATA_DIR}/ - it may be behind production, "
            f"because the write-ahead log is not copied")


def run(args: Any, prompter: Prompter) -> int:
    global LAST_CWD
    project = project_path(getattr(args, "path", None))
    entry = registry.get_project(project)
    ticket = tickets.load(project, args.id)
    if ticket.get("stage") != STAGE:
        raise ConfigError(
            f"Ticket {int(ticket['id']):04d} is at {tickets._label(ticket['stage'])}, not "
            f"⑨ staging. Staging is for a ticket waiting at that checkpoint.")
    if not ticket.get("branch"):
        raise ConfigError(f"Ticket {int(ticket['id']):04d} has no branch to stage.")

    ruleset = constitution.resolve(project)
    staging = ruleset.get(STAGE) or {}
    if not staging.get("compose"):
        raise ConfigError(
            f"{entry['name']} has no staging environment: its profile "
            f"({entry['profile']}) defines none, so there is nothing to bring up. "
            f"A project deployed with Docker Compose gets one.")
    if _docker() is None:
        raise ConfigError("Docker is not installed here, or not on the PATH. `taller stage` "
                          "runs on the machine that hosts the project.")

    worktree = tickets._worktree(project, ticket)
    if not worktree.is_dir():
        raise ConfigError(f"The ticket's working copy is gone ({worktree}). "
                          f"`taller ticket resume {int(ticket['id'])}` recreates it.")
    _refuse_if_git_would_track(worktree)
    data = prepare_data(project, worktree, ruleset)
    argv = command(project, entry["name"], ruleset, executable=_docker() or "docker")
    LAST_CWD = str(worktree)
    completed = _compose(argv, worktree)
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-10:]
        raise ConfigError("Staging did not come up:\n  " + "\n  ".join(tail))

    url = str(staging.get("url") or "")
    status, body = _answers(url, float(staging.get("timeout_s") or 60)) if url else (None, b"")
    if url and (status != 200 or not body.strip()):
        raise ConfigError(
            f"Staging started but {url} did not answer with a page"
            + (f" (it said {status})" if status else "") + ".\n"
            f"Look for yourself: `{' '.join(argv[:-3])} logs app` in {worktree}.")
    prompter.say("\n".join([
        f"Staging for ticket {int(ticket['id']):04d} is up: {url or 'no URL configured'}",
        f"  data: {data}",
        f"  stop it with: {' '.join(argv[:len(argv) - 3])} down",
    ]))
    return 0


def _refuse_if_git_would_track(worktree: Path) -> None:
    """A copy of production data that git would commit is not acceptable (spec 13.1)."""
    from .. import gitio

    probe = f"{DATA_DIR}/probe.db"
    ignored = gitio.git(worktree, "check-ignore", "-q", "--", probe, check=False)
    if ignored.returncode != 0:
        raise ConfigError(
            f"{DATA_DIR}/ is not in this project's .gitignore, so a copy of production "
            f"data there could be committed to the branch. Add a line `{DATA_DIR}/` to "
            f".gitignore, commit it, then run this again.")


def _compose(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """The one place this module runs docker, so a test can stand in for it."""
    return subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=TIMEOUT_S)


def _docker() -> str | None:
    return shutil.which("docker")


def _answers(url: str, timeout_s: float) -> tuple[int | None, bytes]:
    """Poll the staging URL until it answers, or the time is up."""
    import time

    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.status, response.read()
        except (urllib.error.URLError, OSError):
            if time.monotonic() >= deadline:
                return None, b""
            time.sleep(1)
