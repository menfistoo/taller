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

from . import gitio, issues, locking, registry
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
    "id", "slug", "title", "kind", "named_by", "lane", "stage", "branch", "issue", "created",
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


CHECKPOINT_STATES = ("pending", "approved", "rejected", "skipped")


def _parse(raw: bytes | None, where: str, folder: str) -> Ticket:
    """A `status.yml`, checked against the schema and against its own folder.

    Hand edits are expected - the file is on `main` for anyone to open - so every
    field the code reads is checked here, and a bad one is a `ConfigError` naming
    the file rather than a traceback three calls later. The id and slug must
    match the folder: every write rebuilds the path from them, so a renamed slug
    would otherwise start a second folder for the same ticket.
    """
    if raw is None:
        raise ConfigError(f"{where} is missing on {gitio.MAIN_BRANCH}.")
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{where} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{where} must hold a mapping.")

    problems: list[str] = []
    ident, slug = data.get("id"), data.get("slug")
    if not isinstance(ident, int) or isinstance(ident, bool):
        problems.append("`id` must be a number")
    if not isinstance(slug, str) or not slug:
        problems.append("`slug` must be text")
    if not problems and f"{ident:04d}-{slug}" != folder:
        problems.append(f"`id` and `slug` say {ident:04d}-{slug}, but the folder is {folder}")
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        problems.append("`title` is missing")
    if data.get("stage") not in STAGES:
        problems.append(f"`stage: {data.get('stage')}` is not one of the twelve")
    if data.get("kind") not in KINDS:
        problems.append(f"`kind: {data.get('kind')}` is not one of {', '.join(KINDS)}")
    if data.get("lane") not in (None, *LANE_STAGES):
        problems.append(f"`lane: {data.get('lane')}` is not fast or full")
    checkpoints = data.get("checkpoints")
    if not isinstance(checkpoints, dict) or set(checkpoints) != set(CHECKPOINT_AT) or \
            any(state not in CHECKPOINT_STATES for state in checkpoints.values()):
        problems.append("`checkpoints` must give design, review, staging and release "
                        f"each one of {', '.join(CHECKPOINT_STATES)}")
    blocked = data.get("blocked")
    if blocked is not None and (not isinstance(blocked, dict)
                                or not {"reason", "at_stage", "since"} <= set(blocked)):
        problems.append("`blocked` must be empty or give reason, at_stage and since")
    if data.get("sync") not in (None, *gitio.SYNC_STATES):
        problems.append(f"`sync: {data.get('sync')}` is not ok, local or pending")
    if problems:
        raise ConfigError(f"{where}: " + "; ".join(problems) + ".")
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
            found.append(_parse(read_main(project, where), where, name))
        except ConfigError as exc:
            problems.append(str(exc))
    found.sort(key=lambda ticket: int(ticket["id"]))
    return found, problems


def load(project: Path | str, ticket_id: int) -> Ticket:
    prefix = f"{int(ticket_id):04d}-"
    for name in _dirs_on_main(project):
        if name.startswith(prefix):
            where = f"{WORK}/{name}/status.yml"
            return _parse(read_main(project, where), where, name)
    raise ConfigError(f"There is no ticket {ticket_id}. `taller ticket list` shows them.")


def effective_sync(project: Path | str, ticket: Mapping[str, Any]) -> str | None:
    """`sync`, corrected for a later push that carried this ticket's commits.

    `pending` is only rewritten when the same ticket is written again, but any
    ticket's push carries every commit before it. Once `main` is contained in
    what the remote has (the tracking ref a push updates), the mark is stale.
    """
    if ticket.get("sync") != gitio.SYNC_PENDING:
        return ticket.get("sync")
    remote_main = f"refs/remotes/{gitio.REMOTE}/{gitio.MAIN_BRANCH}"
    pushed = gitio.git(project, "merge-base", "--is-ancestor", gitio.MAIN_BRANCH,
                       remote_main, check=False).returncode == 0
    return gitio.SYNC_OK if pushed else gitio.SYNC_PENDING


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
          note: str | None = None, extra: Mapping[str, bytes] | None = None,
          retry_issue: bool = True) -> Ticket:
    """The one path to `main` for a ticket: status, a note, any extra files.

    `status.yml` cannot contain the result of its own push, so `sync` is written
    as expected (`local` with no remote, else `ok`); when the push fails, it is
    corrected to `pending` in one more commit, which stays local until the next
    push carries both (7.3).

    A ticket whose GitHub issue could not be opened at ① gets another attempt
    here, quietly, until it has a number (14).
    """
    entry = registry.get_project(project)
    with locking.project_lock(entry["name"]):
        folder = ticket_dir(ticket)
        if retry_issue and ticket.get("issue") is None and ticket["stage"] != "close":
            number, _ = issues.open_issue(project, {**ticket, "words": _words(project, ticket)})
            if number:
                ticket["issue"] = number
                note = f"{note}; GitHub issue #{number} opened" if note \
                    else f"GitHub issue #{number} opened"
        files: dict[str, bytes] = dict(extra or {})
        if note:
            notes_path = f"{folder}/notes.md"
            existing = files.get(notes_path) or read_main(project, notes_path) or b""
            files[notes_path] = existing + f"- {_now()} — {note}\n".encode("utf-8")
        ticket["sync"] = "ok" if _has_origin(project) else "local"
        files[f"{folder}/status.yml"] = render_status(ticket)
        state = gitio.commit_to_main(project, files, message)
        if state == gitio.SYNC_PENDING:
            # Everything again, not only the status: `pending` also means the
            # first commit may never have reached `main` (a lost compare-and-swap,
            # 7.3), and the files are whole files, so resending them is harmless.
            ticket["sync"] = gitio.SYNC_PENDING
            files[f"{folder}/status.yml"] = render_status(ticket)
            gitio.commit_to_main(project, files, f"{message} (not pushed yet)")
    return ticket


def create(project: Path | str, *, title: str, words: str, kind: str,
           named_by: str | None = "owner") -> Ticket:
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
            "created": created, "outcome": None, "named_by": named_by,
            "gates": [], "verdicts": {},
            "blocked": None, "fix_rounds": 0, "chief_session": None, "sync": None,
            "templates": {},
            "checkpoints": {name: "pending" for name in CHECKPOINT_AT},
            "spend": {"partial": False, "by_model": {}, "total_tokens": 0,
                      "weighted_tokens": 0, "cost": None},
        }
        body = str(words) if str(words).endswith("\n") else f"{words}\n"
        ticket_md = (f"# {title}\n\n- Kind: {kind}\n- Created: {created}\n\n"
                     f"{WORDS_HEADING}\n\n{body}")
        folder = ticket_dir(ticket)
        number, reason = issues.open_issue(project, {**ticket, "words": words})
        ticket["issue"] = number
        note = "created at ① intake"
        if number:
            note += f"; GitHub issue #{number}"
        elif reason:
            note += f"; GitHub issue not opened ({reason}) - retried at the next move"
        return write(project, ticket, f"ticket {ticket['id']:04d}: {title}", note=note,
                     extra={f"{folder}/ticket.md": ticket_md.encode("utf-8")},
                     retry_issue=False)


WORDS_HEADING = "## In the owner's words"


def _words(project: Path | str, ticket: Mapping[str, Any]) -> str:
    """The owner's words back out of `ticket.md`, for a retried issue's body."""
    raw = read_main(project, f"{ticket_dir(ticket)}/ticket.md")
    text = raw.decode("utf-8", errors="replace") if raw else ""
    return text.split(f"{WORDS_HEADING}\n\n", 1)[1] if WORDS_HEADING in text else ""


def _close_issue_note(project: Path | str, ticket: Mapping[str, Any]) -> str:
    if not ticket.get("issue"):
        return ""
    failure = issues.close_issue(project, ticket)
    return (f"; GitHub issue #{ticket['issue']} not closed ({failure})" if failure
            else f"; GitHub issue #{ticket['issue']} closed")


# --- the stage machine (spec 8) ------------------------------------------------

NUMERALS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫"


def _label(stage: str) -> str:
    return f"{NUMERALS[stage_number(stage) - 1]} {stage}"


def next_stage(ticket: Mapping[str, Any]) -> str | None:
    """The stage after this one in the ticket's lane; None once closed.

    Before ② decides, `intake` → `triage` is the same in both lanes.
    """
    order = LANE_STAGES[ticket.get("lane") or "full"]
    index = order.index(ticket["stage"])
    return order[index + 1] if index + 1 < len(order) else None


def _name(ticket: Mapping[str, Any]) -> str:
    return ticket_dir(ticket).split("/")[-1]


def _worktree(project: Path, ticket: Mapping[str, Any]) -> Path:
    from . import paths
    return paths.ticket_worktree(registry.get_project(project)["name"], _name(ticket))


def _branch_exists(project: Path, branch: str) -> bool:
    return gitio.git(project, "rev-parse", "--verify", "--quiet",
                     f"refs/heads/{branch}", check=False).returncode == 0


def _open_worktree(project: Path, ticket: Ticket) -> None:
    """④ build: the branch from `main`, and a worktree attached to it (8.1, 8.3)."""
    branch = f"ticket/{_name(ticket)}"
    if not _branch_exists(project, branch):
        gitio.git(project, "branch", branch, gitio.MAIN_BRANCH)
    tree = _worktree(project, ticket)
    tree.parent.mkdir(parents=True, exist_ok=True)
    gitio.git(project, "worktree", "prune")
    if gitio._is_worktree(tree):
        # Left by an attempt whose write failed after this point: reuse it, or
        # the ticket could never leave triage again.
        holds = gitio.git(tree, "symbolic-ref", "--quiet", "--short", "HEAD",
                          check=False).stdout.strip()
        if holds != branch:
            raise ConfigError(f"{tree} is a worktree on {holds or 'a detached HEAD'}, not "
                              f"{branch}. Remove it (`git worktree remove {tree}`) and retry.")
    else:
        gitio.git(project, "worktree", "add", "--quiet", str(tree), branch)
    ticket["branch"] = branch


def _merged(project: Path, branch: str) -> bool:
    return gitio.git(project, "merge-base", "--is-ancestor", branch, gitio.MAIN_BRANCH,
                     check=False).returncode == 0


def _clean_up(project: Path, ticket: Ticket, *, delete_unmerged: bool,
              strict: bool = False) -> list[str]:
    """Remove the worktree; delete the branch when merged (or when told to).

    Returns what it did, for `notes.md` - what actually happened, not what was
    attempted. `strict` raises instead: a rejection must not move the ticket on
    while its rejected branch survives, or the next attempt would build on it
    (7.6). On Windows a program with its folder open is enough to make removal
    fail.
    """
    done: list[str] = []
    tree = _worktree(project, ticket)
    if tree.exists():
        result = gitio.git(project, "worktree", "remove", "--force", str(tree), check=False)
        if result.returncode != 0:
            reason = (result.stderr or result.stdout or "").strip()
            if strict:
                raise ConfigError(f"Could not remove the worktree at {tree}: {reason}. "
                                  f"Close anything using that folder and run the command "
                                  f"again; nothing has been changed.")
            done.append(f"worktree not removed ({reason})")
        else:
            done.append("worktree removed")
    gitio.git(project, "worktree", "prune", check=False)
    branch = ticket.get("branch")
    if branch and _branch_exists(project, branch):
        if delete_unmerged or _merged(project, branch):
            result = gitio.git(project, "branch", "-D", branch, check=False)
            if result.returncode != 0 and strict:
                raise ConfigError(f"Could not delete {branch}: {result.stderr.strip()}. "
                                  f"Nothing has been changed; run the command again.")
            done.append(f"branch {branch} deleted" if result.returncode == 0
                        else f"branch {branch} kept: {result.stderr.strip()}")
        else:
            done.append(f"branch {branch} kept: not merged")
    return done


def _refuse_if_blocked(ticket: Mapping[str, Any]) -> None:
    if ticket.get("blocked"):
        raise ConfigError(
            f"Ticket {ticket['id']} is blocked: {ticket['blocked']['reason']}. "
            f"`taller ticket resume {ticket['id']}` once that is dealt with.")


def advance(project: Path | str, ticket_id: int, *, lane: str | None = None,
            note: str | None = None, fields: Mapping[str, Any] | None = None) -> Ticket:
    """Move to the next stage of the ticket's lane, doing what entering it needs.

    `fields` are set on the ticket in the same commit (the explorer's `templates`).
    """
    project = Path(project)
    with locking.project_lock(registry.get_project(project)["name"]):
        ticket = load(project, ticket_id)
        _refuse_if_blocked(ticket)
        ticket.update(fields or {})
        stage = ticket["stage"]
        if stage == "close":
            raise ConfigError(f"Ticket {ticket_id} is closed.")

        detail = ""
        if lane is not None or stage == "triage":
            detail = _set_lane(ticket, lane)
        checkpoint = CHECKPOINT_AT.get(stage)
        if checkpoint and ticket["checkpoints"][checkpoint] != "approved":
            raise ConfigError(
                f"Ticket {ticket_id} is at the {checkpoint} checkpoint ({_label(stage)}). "
                f"`taller ticket approve {ticket_id}` approves it and moves on; "
                f"`taller ticket reject {ticket_id}` sends it back.")

        target = next_stage(ticket)
        extra = ""
        if target == "build":
            _open_worktree(project, ticket)
            extra = f"; branch {ticket['branch']}"
        elif target == "merge":
            if not _merged(project, ticket["branch"]):
                raise ConfigError(
                    f"{ticket['branch']} is not merged into {gitio.MAIN_BRANCH} yet. "
                    f"Merge it (its pull request, or `git merge {ticket['branch']}` on "
                    f"{gitio.MAIN_BRANCH}), then move the ticket on.")
        elif target == "close":
            ticket["outcome"] = "done"
            done = _clean_up(project, ticket, delete_unmerged=False)
            extra = (f"; {', '.join(done)}" if done else "") + _close_issue_note(project, ticket)
        ticket["stage"] = target
        return write(project, ticket, f"ticket {ticket_id:04d}: {stage} -> {target}",
                     note=f"{_label(stage)} → {_label(target)}{detail}{extra}"
                          + (f"; {note}" if note else ""))


def _set_lane(ticket: Ticket, lane: str | None) -> str:
    """② chooses the lane, once (8.2). Returns the note fragment."""
    if ticket["stage"] != "triage":
        raise ConfigError("The lane is chosen at ② triage, and only there.")
    if lane is None:
        if ticket.get("lane"):
            return ""
        raise ConfigError(
            f"Ticket {ticket['id']} needs a lane before it leaves triage: "
            f"`taller ticket transition {ticket['id']} --lane fast` for a small, safe "
            f"change in one file, `--lane full` for anything else.")
    if lane not in LANE_STAGES:
        raise ConfigError(f"{lane!r} is not a lane; use fast or full.")
    if ticket.get("lane") == "full" and lane == "fast":
        raise ConfigError(f"Ticket {ticket['id']}'s lane is already full; a lane is "
                          f"never demoted (spec 8.2).")
    ticket["lane"] = lane
    if lane == "fast":
        ticket["checkpoints"]["design"] = "skipped"
        ticket["checkpoints"]["staging"] = "skipped"
    else:
        # Promoted from fast, e.g. at a re-triage after a rejection: the two
        # lane-dependent checkpoints apply again.
        for checkpoint in ("design", "staging"):
            if ticket["checkpoints"][checkpoint] == "skipped":
                ticket["checkpoints"][checkpoint] = "pending"
    return f" (lane {lane})"


def approve(project: Path | str, ticket_id: int) -> Ticket:
    """Record the owner's approval at this stage's checkpoint, then move on."""
    project = Path(project)
    with locking.project_lock(registry.get_project(project)["name"]):
        ticket = load(project, ticket_id)
        _refuse_if_blocked(ticket)
        checkpoint = CHECKPOINT_AT.get(ticket["stage"])
        if checkpoint is None:
            raise ConfigError(
                f"Ticket {ticket_id} is at {_label(ticket['stage'])}, which is not a "
                f"checkpoint. Checkpoints are ③ design, ⑦ review, ⑨ staging, ⑪ release.")
        ticket["checkpoints"][checkpoint] = "approved"
        write(project, ticket, f"ticket {ticket_id:04d}: {checkpoint} approved",
              note=f"{checkpoint} approved by the owner")
        return advance(project, ticket_id)


def reject(project: Path | str, ticket_id: int, reason: str) -> Ticket:
    """The owner says no at a checkpoint (14).

    At ⑦ review, exactly as the spec says: the evidence and the reason go to `main`
    first, then the worktree and branch go, and the ticket returns to ② with a
    fresh chief conversation (7.6). At ③, ⑨ and ⑪ the ticket stays where it is,
    blocked with the reason, until the owner resumes it.
    """
    project = Path(project)
    reason = str(reason).strip()
    if not reason:
        raise ConfigError("A rejection needs a reason; it is what the next attempt reads.")
    with locking.project_lock(registry.get_project(project)["name"]):
        ticket = load(project, ticket_id)
        stage = ticket["stage"]
        checkpoint = CHECKPOINT_AT.get(stage)
        if checkpoint is None:
            raise ConfigError(f"Ticket {ticket_id} is at {_label(stage)}, which is not a "
                              f"checkpoint, so there is nothing to reject.")
        if stage != "review":
            ticket["checkpoints"][checkpoint] = "rejected"
            ticket["blocked"] = {"reason": f"rejected at {_label(stage)}: {reason}",
                                 "at_stage": stage_number(stage), "since": _now()}
            return write(project, ticket, f"ticket {ticket_id:04d}: {checkpoint} rejected",
                         note=f"{checkpoint} rejected: {reason}")

        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        kept = f"{ticket_dir(ticket)}/rejected/{stamp}"
        evidence: dict[str, bytes] = {f"{kept}/reason.md": f"{reason}\n".encode("utf-8")}
        evidence.update({f"{kept}/gates/{relative}": data
                         for relative, data in _gate_files(project, ticket).items()})
        gitio.commit_to_main(project, evidence, f"ticket {ticket_id:04d}: keep rejected work")

        done = _clean_up(project, ticket, delete_unmerged=True, strict=True)
        ticket.update({"stage": "triage", "branch": None, "chief_session": None,
                       "gates": [], "verdicts": {}, "fix_rounds": 0})
        ticket["checkpoints"]["review"] = "pending"
        if ticket.get("lane") == "full":
            ticket["checkpoints"]["design"] = "pending"
        return write(project, ticket, f"ticket {ticket_id:04d}: rejected at review",
                     note=f"rejected at ⑦ review: {reason}. Kept under {kept}; "
                          f"{', '.join(done) or 'nothing to clean up'}. Back to ② triage.")


def _gate_files(project: Path, ticket: Mapping[str, Any]) -> dict[str, bytes]:
    """The ticket's verdicts, from the worktree - or from the branch when a killed
    session took the worktree with it, so §14's evidence survives either way."""
    gates = _worktree(project, ticket) / ticket_dir(ticket) / "gates"
    if gates.is_dir():
        return {file.relative_to(gates).as_posix(): file.read_bytes()
                for file in sorted(gates.rglob("*")) if file.is_file()}
    branch = ticket.get("branch")
    if not branch or not _branch_exists(project, branch):
        return {}
    prefix = f"{ticket_dir(ticket)}/gates/"
    listed = gitio.git(project, "ls-tree", "-r", "--name-only", branch, "--", prefix,
                       check=False).stdout.split()
    found: dict[str, bytes] = {}
    for path in listed:
        blob = subprocess.run(["git", "-C", str(project), "cat-file", "blob",
                               f"{branch}:{path}"], capture_output=True)
        if blob.returncode == 0:
            found[path[len(prefix):]] = blob.stdout
    return found


def block(project: Path | str, ticket_id: int, reason: str) -> Ticket:
    """Stop at the current stage with a reason; the stage is kept (8.4)."""
    project = Path(project)
    with locking.project_lock(registry.get_project(project)["name"]):
        ticket = load(project, ticket_id)
        ticket["blocked"] = {"reason": str(reason), "at_stage": stage_number(ticket["stage"]),
                             "since": _now()}
        return write(project, ticket, f"ticket {ticket_id:04d}: blocked",
                     note=f"blocked at {_label(ticket['stage'])}: {reason}")


def resume(project: Path | str, ticket_id: int) -> tuple[Ticket, list[str]]:
    """Pick a ticket up from disk after anything - a block, a killed session (G5).

    Clears `blocked` and repairs what a dead process can leave behind: a ticket
    past ④ whose worktree is gone gets it back from its branch. A missing branch
    is reported, never invented - the work on it would be.
    """
    project = Path(project)
    with locking.project_lock(registry.get_project(project)["name"]):
        ticket = load(project, ticket_id)
        repairs: list[str] = []
        if ticket.get("blocked"):
            repairs.append(f"unblocked (was: {ticket['blocked']['reason']})")
            ticket["blocked"] = None
        working = stage_number("build") <= stage_number(ticket["stage"]) < stage_number("merge")
        if working and ticket.get("branch"):
            if not _branch_exists(project, ticket["branch"]):
                repairs.append(f"branch {ticket['branch']} is missing - its work cannot "
                               f"be recovered from the ticket; reject or close it")
            elif not _worktree(project, ticket).is_dir():
                _open_worktree(project, ticket)
                repairs.append(f"worktree recreated on {ticket['branch']}")
        if repairs:
            write(project, ticket, f"ticket {ticket_id:04d}: resumed",
                  note="resumed: " + "; ".join(repairs))
        return ticket, repairs


def close(project: Path | str, ticket_id: int, *, abandon_reason: str | None = None) -> Ticket:
    """⑫: from ⑪ with the release approved, or abandoned from anywhere."""
    project = Path(project)
    with locking.project_lock(registry.get_project(project)["name"]):
        ticket = load(project, ticket_id)
        if ticket["stage"] == "close":
            raise ConfigError(f"Ticket {ticket_id} is already closed.")
        if abandon_reason is None:
            if ticket["stage"] != "release" or ticket["checkpoints"]["release"] != "approved":
                raise ConfigError(
                    f"Ticket {ticket_id} closes after its release is approved "
                    f"(`taller ticket approve {ticket_id}` at ⑪ release). To stop it "
                    f"early, close it with a reason for abandoning it.")
            return advance(project, ticket_id)
        done = _clean_up(project, ticket, delete_unmerged=False)
        stage = ticket["stage"]
        ticket.update({"stage": "close", "outcome": "abandoned", "blocked": None})
        return write(project, ticket, f"ticket {ticket_id:04d}: abandoned",
                     note=f"abandoned at {_label(stage)}: {abandon_reason}"
                          + (f"; {', '.join(done)}" if done else "")
                          + _close_issue_note(project, ticket))
