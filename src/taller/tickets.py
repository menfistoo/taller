"""Tickets: the files on `main` that carry a piece of work through twelve stages.

Spec 7.1, 7.2, 8. A ticket is `.taller/work/NNNN-slug/` holding `ticket.md` (the
owner's words, verbatim), `status.yml` (machine state) and `notes.md` (decisions
and why, append-only). All three live on `main` and are written only through
`gitio.commit_to_main()`, under the project lock (10.3).

**Tickets are read from `main`, never from the working tree.** The owner's
checkout may be on a ticket branch, whose `.taller/work/` is frozen at the
moment it was cut: reading there would list stale tickets and reuse an id.
"""

from __future__ import annotations

import re
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from . import gitio, locking, registry
from .errors import ConfigError
from .scaffold import flatten

Ticket = dict[str, Any]

# Spec 8.1, in order. `status.yml` holds the name.
STAGES: tuple[str, ...] = (
    "intake", "triage", "design", "build", "gates", "smoke",
    "review", "pr", "staging", "merge", "release", "close",
)
# Spec 8.2: fast skips design and staging.
LANE_STAGES: dict[str, tuple[str, ...]] = {
    "full": STAGES,
    "fast": tuple(stage for stage in STAGES if stage not in ("design", "staging")),
}
# The four owner checkpoints, each at the stage of the same name.
CHECKPOINT_AT: dict[str, str] = {"design": "design", "review": "review",
                                 "staging": "staging", "release": "release"}
KINDS: tuple[str, ...] = ("bug", "feature", "refactor", "question", "idea")

WORK = ".taller/work"
_DIR = re.compile(r"^(\d{4})-[a-z0-9-]+$")
SLUG_MAX = 40
TITLE_MAX = 120

# Spec 7.1's order, so status.yml diffs read the same way every time.
STATUS_KEYS = (
    "id", "slug", "title", "kind", "lane", "stage", "branch", "issue", "created",
    "outcome", "gates", "verdicts", "blocked", "fix_rounds", "chief_session", "sync",
    "templates", "checkpoints", "spend",
)


# --- names -------------------------------------------------------------------

def slugify(title: str) -> str:
    """ASCII, hyphenated, at most 40 characters, never empty."""
    text = unicodedata.normalize("NFKD", str(title))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:SLUG_MAX].strip("-") or "ticket"


def ticket_dir(ticket: Mapping[str, Any]) -> str:
    return f"{WORK}/{int(ticket['id']):04d}-{ticket['slug']}"


def stage_number(stage: str) -> int:
    return STAGES.index(stage) + 1


# --- reading from main -------------------------------------------------------

def read_main(project: Path | str, relative: str) -> bytes | None:
    """A file as `main` has it, or None when `main` does not have it."""
    completed = subprocess.run(
        ["git", "-C", str(project), "cat-file", "blob", f"{gitio.MAIN_BRANCH}:{relative}"],
        capture_output=True)
    return completed.stdout if completed.returncode == 0 else None


def _dirs_on_main(project: Path | str) -> list[str]:
    completed = gitio.git(project, "ls-tree", "--name-only", f"{gitio.MAIN_BRANCH}:{WORK}",
                          check=False)
    if completed.returncode != 0:
        return []                                        # no ticket yet
    return sorted(name for name in completed.stdout.split() if _DIR.match(name))


def _parse(raw: bytes | None, where: str) -> Ticket:
    if raw is None:
        raise ConfigError(f"{where} is missing on {gitio.MAIN_BRANCH}.")
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{where} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{where} must hold a mapping.")
    for key in ("id", "slug", "stage"):
        if key not in data:
            raise ConfigError(f"{where} has no `{key}`.")
    if data["stage"] not in STAGES:
        raise ConfigError(f"{where}: `stage: {data['stage']}` is not one of the twelve.")
    return data


def list_tickets(project: Path | str) -> tuple[list[Ticket], list[str]]:
    """Every ticket on `main` by id, and a line for each one that would not load.

    A broken `status.yml` is reported, not raised: one hand-edited file must not
    hide every other ticket.
    """
    found: list[Ticket] = []
    problems: list[str] = []
    for name in _dirs_on_main(project):
        where = f"{WORK}/{name}/status.yml"
        try:
            found.append(_parse(read_main(project, where), where))
        except ConfigError as exc:
            problems.append(str(exc))
    found.sort(key=lambda ticket: int(ticket["id"]))
    return found, problems


def load(project: Path | str, ticket_id: int) -> Ticket:
    prefix = f"{int(ticket_id):04d}-"
    for name in _dirs_on_main(project):
        if name.startswith(prefix):
            where = f"{WORK}/{name}/status.yml"
            return _parse(read_main(project, where), where)
    raise ConfigError(f"There is no ticket {ticket_id}. `taller ticket list` shows them.")


def _next_id(project: Path | str) -> int:
    ids = [int(_DIR.match(name).group(1)) for name in _dirs_on_main(project)]
    return max(ids, default=0) + 1


# --- writing -----------------------------------------------------------------

def render_status(ticket: Mapping[str, Any]) -> bytes:
    ordered = {key: ticket.get(key) for key in STATUS_KEYS}
    ordered.update({key: value for key, value in ticket.items() if key not in ordered})
    return yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False).encode("utf-8")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _has_origin(project: Path | str) -> bool:
    return gitio.git(project, "config", "--get", f"remote.{gitio.REMOTE}.url",
                     check=False).returncode == 0


def write(project: Path | str, ticket: Ticket, message: str, *,
          note: str | None = None, extra: Mapping[str, bytes] | None = None) -> Ticket:
    """The one path to `main` for a ticket: status, a note, any extra files.

    `status.yml` cannot contain the result of its own push, so `sync` is written
    as expected (`local` with no remote, else `ok`); when the push fails, it is
    corrected to `pending` in one more commit, which stays local until the next
    push carries both (7.3).
    """
    entry = registry.get_project(project)
    with locking.project_lock(entry["name"]):
        folder = ticket_dir(ticket)
        files: dict[str, bytes] = dict(extra or {})
        if note:
            notes_path = f"{folder}/notes.md"
            existing = files.get(notes_path) or read_main(project, notes_path) or b""
            files[notes_path] = existing + f"- {_now()} — {note}\n".encode("utf-8")
        ticket["sync"] = "ok" if _has_origin(project) else "local"
        files[f"{folder}/status.yml"] = render_status(ticket)
        state = gitio.commit_to_main(project, files, message)
        if state == gitio.SYNC_PENDING:
            ticket["sync"] = gitio.SYNC_PENDING
            gitio.commit_to_main(project, {f"{folder}/status.yml": render_status(ticket)},
                                 f"{message} (not pushed yet)")
    return ticket


def create(project: Path | str, *, title: str, words: str, kind: str) -> Ticket:
    """Stage ① intake: the owner's words, verbatim, committed to `main`."""
    title = flatten(title)[:TITLE_MAX]
    if not title:
        raise ConfigError("A ticket needs a title.")
    if not str(words).strip():
        raise ConfigError("A ticket needs the owner's words: what should be done.")
    if kind not in KINDS:
        raise ConfigError(f"{kind!r} is not a kind of ticket; use one of {list(KINDS)}.")

    entry = registry.get_project(project)
    with locking.project_lock(entry["name"]):
        created = _now()
        ticket: Ticket = {
            "id": _next_id(project), "slug": slugify(title), "title": title, "kind": kind,
            "lane": None, "stage": "intake", "branch": None, "issue": None,
            "created": created, "outcome": None, "gates": [], "verdicts": {},
            "blocked": None, "fix_rounds": 0, "chief_session": None, "sync": None,
            "templates": {},
            "checkpoints": {name: "pending" for name in CHECKPOINT_AT},
            "spend": {"partial": False, "by_model": {}, "total_tokens": 0,
                      "weighted_tokens": 0, "cost": None},
        }
        body = str(words) if str(words).endswith("\n") else f"{words}\n"
        ticket_md = (f"# {title}\n\n- Kind: {kind}\n- Created: {created}\n\n"
                     f"## In the owner's words\n\n{body}")
        folder = ticket_dir(ticket)
        return write(project, ticket, f"ticket {ticket['id']:04d}: {title}",
                     note="created at ① intake",
                     extra={f"{folder}/ticket.md": ticket_md.encode("utf-8")})
