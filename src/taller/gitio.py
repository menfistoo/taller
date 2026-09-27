"""The `main` worktree, and the only write path to a project's `main` branch.

Spec 7.3. Roughly a dozen times per ticket Taller must write a file that has to be
visible from `main` — the ticket, its status, its notes, the three generated files
of spec 4.6 — while the work itself sits on a ticket branch. Switching the owner's
own checkout to `main` to do that would risk a half-migrated schema against a live
write-ahead log, so Taller keeps a long-lived worktree of `main` at
`~/.taller-run/worktrees/<project>-main/`, outside both the project tree and the
hub repository, and writes there.

`main` normally requires a pull request. The owner's admin bypass is retained and
used **only** by `commit_to_main()`, and only for spec 7.2's paths. A path outside
that set is a programming error rather than a runtime condition, so it raises
instead of returning a failed result — the same distinction `inference.py` draws
between a contract violation and a failure of the thing being contracted.

Two decisions worth their explanation:

**Why `main` is never shared between two worktrees.** An earlier version created
this worktree with `worktree add --force ... main`, because git refuses a second
checkout of a checked-out branch and the owner's own checkout is on `main` at
`project adopt` and at the end of `project new`. The two worktrees then shared one
branch ref, and that is a data-loss bug **in both directions**, verified each way:

- A commit the owner made left this worktree's index holding a staged *deletion*
  of the owner's file, which the next Taller commit carried to `main`. An automatic
  `reset --hard` closed that direction.
- It left the other open. A Taller commit left the owner's index holding a staged
  deletion of *Taller's* file, and the owner's next ordinary commit - any commit,
  nothing unusual - carried that to `main`, taking the rules snapshot with it.

When a fix leaves the mirror image of its bug behind, the design is wrong, not the
fix. So `main` is never checked out here at all. There are two write paths,
chosen by where the owner's own checkout is:

| Owner's checkout | How Taller writes |
|---|---|
| on any other branch, or detached - the normal ticket flow | In this worktree, which sits on a **detached** head. Commit there, then advance `refs/heads/main` by compare-and-swap. Nobody has `main` checked out, so nothing desynchronises. |
| **on `main`** | **Into the owner's own checkout**, committing **only** the named paths with `git commit --only`. Their other staged and unstaged work is untouched, and their index knows about the change, so nothing appears deleted and nothing gets deleted. |

The original reason for keeping Taller out of the owner's checkout was switching
branches under a running application with a live database. Committing named files
on the branch they are already on switches nothing, so it does not apply.

In the second path Taller never rewrites the owner's branch: no rebase, no merge.
If the remote has moved, the commit stays local and the state is `pending`. And it
refuses outright - raising rather than returning - if the owner is mid-merge or
mid-rebase, or has uncommitted changes to a path Taller is about to write, because
proceeding would destroy work and recording nothing is better than that.

**Why `sync` is a returned value and not an assumed invariant.** Commit and push
are not atomic and spec 10.3's atomic replace covers files only, so the state of
the remote is reported rather than promised. Local state is the truth; the remote
is a mirror. Every failure degrades to `pending` and loses no transition.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from . import catalogue, config, locking, paths, registry
from .errors import ConfigError, GitError

Project = dict[str, Any]

# Spec 7.3's three values. `local` is not a fault and `doctor` ignores it; `pending`
# is a remote that has not caught up and `doctor` reports it.
SyncState = str
SYNC_OK = "ok"
SYNC_LOCAL = "local"
SYNC_PENDING = "pending"
SYNC_STATES = (SYNC_OK, SYNC_LOCAL, SYNC_PENDING)

MAIN_BRANCH = "main"
REMOTE = "origin"

# Generous: a push over a slow link is legitimate. Finite: a credential prompt that
# slipped past GIT_TERMINAL_PROMPT would otherwise hold the project lock for ever.
GIT_TIMEOUT = 300.0

# Bounds the resolve-and-continue loop below. A rebase of the main-side paths
# replays a handful of commits at most; anything more is a symptom, not a workload.
MAX_REBASE_STEPS = 20

# --- spec 7.2's allowed list, and nothing else -------------------------------

TICKET_FILES = frozenset({"ticket.md", "status.yml", "notes.md"})
REJECTED_DIR = "rejected"
TALLER_DIR = ".taller"
WORK_DIR = "work"

FIXED_ALLOWED = (
    f"{TALLER_DIR}/resolved.json",
    f"{TALLER_DIR}/constitution/00-index.md",
    ".gitattributes",
)

ALLOWED_DESCRIPTION = (
    f"{TALLER_DIR}/{WORK_DIR}/<ticket>/{{{', '.join(sorted(TICKET_FILES))}}}, "
    f"{TALLER_DIR}/{WORK_DIR}/<ticket>/{REJECTED_DIR}/**, "
    + ", ".join(FIXED_ALLOWED)
    + ", and the profile's `paths.brand_tokens`"
)


# --- running git -------------------------------------------------------------

def _env() -> dict[str, str]:
    """Git's environment for every call in this module.

    `GIT_TERMINAL_PROMPT=0` is the load-bearing one: a remote that wants
    credentials must *fail* so the push degrades to `sync: pending`, rather than
    block on a prompt nobody is watching while holding the project lock. The two
    editor variables let `rebase --continue` run unattended.
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_EDITOR"] = "true"
    env["GIT_SEQUENCE_EDITOR"] = "true"
    return env


def _git(cwd: Path | str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """One git invocation. `check=False` for the calls whose failure is a state."""
    command = ["git", "-C", str(cwd), *args]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=GIT_TIMEOUT, env=_env(),
        )
    except FileNotFoundError as exc:
        raise GitError(
            "`git` is not on PATH. Taller writes every main-side file through git, "
            "so there is no degraded mode without it."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(
            f"`git {' '.join(args)}` in {cwd} did not finish within {GIT_TIMEOUT:g}s."
        ) from exc
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise GitError(f"`git {' '.join(args)}` failed in {cwd}:\n{detail}")
    return completed


def git(cwd: Path | str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """`_git` for other modules: the same environment, timeout and errors.

    `scaffold.create_project` runs `git init` and the first commit through this,
    so a missing git or a hung prompt fails the same way everywhere.
    """
    return _git(cwd, *args, check=check)


def _ok(cwd: Path | str, *args: str) -> bool:
    return _git(cwd, *args, check=False).returncode == 0


# --- which project ------------------------------------------------------------

def _project_entry(project: Project | Path | str) -> Project:
    """A registry entry, whether the caller had one or only a path.

    Both, because `project adopt` already holds the entry it just wrote and every
    later caller holds a path. Looking it up twice would be the only alternative.
    """
    if isinstance(project, Mapping):
        missing = {"path", "name"} - set(project)
        if missing:
            raise GitError(
                f"A project entry needs {', '.join(sorted(missing))}; got keys "
                f"{', '.join(sorted(project))}."
            )
        return dict(project)
    return registry.get_project(project)


def brand_tokens_path(project: Project | Path | str) -> str | None:
    """The project's `paths.brand_tokens`, or `None` when it has none.

    The one allowed path that lives inside the application's own tree, and a
    profile key rather than a constant: `static/css/tokens.css` for
    `flask-sqlite`, `tokens.css` for `static-site` whose assets sit at the
    repository root, and unset for `python-packaged`, which has no brand (spec
    7.2). Chain 1's order, hub then profile then project, resolved for this one
    key — a full `constitution.resolve()` would make a dozen git writes per ticket
    depend on the hub's module inventory being intact.
    """
    entry = _project_entry(project)
    layers: list[Mapping[str, Any]] = [config.load_hub_config().get("paths") or {}]
    if entry.get("profile"):
        try:
            layers.append(catalogue.read_hub_profile(entry["profile"]).get("paths") or {})
        except ConfigError:
            pass                # an uninstalled profile cannot widen the list
    layers.append(config.read_project_config(Path(entry["path"])).get("paths") or {})

    value: Any = None
    for layer in layers:
        if "brand_tokens" in layer:
            value = layer["brand_tokens"]
    if not value:
        return None
    return str(value).replace("\\", "/").strip("/")


# --- the worktree -------------------------------------------------------------

def ensure_main_worktree(project: Project | Path | str) -> Path:
    """The project's `main` worktree, creating it if needed. Idempotent.

    Idempotent because it runs on every `commit_to_main()`, not only at adopt.
    """
    entry = _project_entry(project)
    repo = Path(entry["path"])
    worktree = paths.main_worktree(entry["name"])
    _assert_outside(worktree, repo)

    if not (repo / ".git").exists():
        raise GitError(
            f"{repo} is not a git repository. Taller writes the ticket and the "
            f"generated files to `{MAIN_BRANCH}`, so there is nothing to write to. "
            f"`taller project new` creates the repository; `taller project adopt` "
            f"expects one."
        )

    if _is_worktree(worktree):
        _detach_if_attached(worktree)
        return worktree

    if not _ok(repo, "rev-parse", "--verify", "--quiet", "HEAD"):
        raise GitError(
            f"{repo} has no commits yet, and git cannot create a worktree in a "
            f"repository with no commits. Make the first commit first: on the "
            f"greenfield path `taller project new` commits its scaffold and only "
            f"then creates this worktree (spec 7.3)."
        )
    if not _ok(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{MAIN_BRANCH}"):
        raise GitError(
            f"{repo} has no `{MAIN_BRANCH}` branch. Taller's ticket and generated "
            f"files must be visible from `{MAIN_BRANCH}` or the cockpit reports "
            f"nothing (spec 7.2). Rename the default branch and retry."
        )

    # Reclaims a worktree whose directory was deleted by hand, which git still
    # lists and would otherwise refuse to recreate.
    _git(repo, "worktree", "prune")
    if worktree.exists() and any(worktree.iterdir()):
        raise GitError(
            f"{worktree} already exists but is not a git worktree. Taller owns "
            f"that directory; remove it and retry."
        )
    worktree.parent.mkdir(parents=True, exist_ok=True)
    # --detach, never a checkout of `main`: see the module docstring. A detached
    # head holds no branch, so git needs no --force and the owner can always
    # check `main` out themselves.
    _git(repo, "worktree", "add", "--detach", str(worktree), MAIN_BRANCH)
    return worktree


def _detach_if_attached(worktree: Path) -> None:
    """Free `main` in a worktree an earlier version created attached to it.

    Earlier installs checked `main` out here with --force. Detaching releases the
    branch without moving anything, so an existing install heals itself on its
    next write instead of needing a manual step.
    """
    if _ok(worktree, "symbolic-ref", "--quiet", "HEAD"):
        _git(worktree, "checkout", "--quiet", "--detach")


def _is_worktree(path: Path) -> bool:
    """A linked worktree carries a `.git` *file* pointing at the real git dir."""
    return (path / ".git").is_file() and _ok(path, "rev-parse", "--git-dir")


def _assert_outside(worktree: Path, repo: Path) -> None:
    """The worktree is outside the project tree and outside the hub (spec 7.3).

    Nested, a hub amendment's `git add -A` would sweep a whole project checkout
    into the hub repository, and the project's own tooling would see a second copy
    of itself. `paths.main_worktree()` already places it under `~/.taller-run/`;
    this turns a regression there into a clear failure rather than a strange one.
    """
    candidates = [(repo, "the project tree"), (paths.hub(), "the hub repository")]
    for other, label in candidates:
        try:
            nested = worktree.resolve().is_relative_to(other.resolve())
        except OSError:                     # an unresolvable path is not nested
            continue
        if nested:
            raise GitError(
                f"The `{MAIN_BRANCH}` worktree {worktree} would be inside {label} "
                f"({other}). Spec 7.3 requires it outside both."
            )


# --- the write ----------------------------------------------------------------

def commit_to_main(
    project: Project | Path | str,
    files: Mapping[str, bytes | str],
    message: str,
) -> SyncState:
    """Write `files` to the project's `main` branch and report the sync state.

    `files` maps a path relative to the project root to its bytes; a `str` is
    encoded UTF-8. Every path must be on spec 7.2's allowed list or this raises,
    before anything is written. An empty mapping is a pure sync retry, which is
    what makes `sync: pending` self-healing: the next call's push carries the
    commit that the failed one left behind.

    Returns `ok`, `local` or `pending` (spec 7.3). Never raises because a remote
    was unreachable — that is the `pending` state, not an error.
    """
    entry = _project_entry(project)
    if not message.strip():
        raise GitError("A commit to `main` needs a message; got an empty one.")

    payload = {_relative(raw): _lf_bytes(data) for raw, data in files.items()}
    _assert_allowed(payload, entry)

    with locking.project_lock(entry["name"]):
        repo = Path(entry["path"])
        if _current_branch(repo) == MAIN_BRANCH:
            return _commit_in_owner_checkout(repo, payload, message)
        return _commit_in_worktree(entry, payload, message)


# --- path 1: the owner is elsewhere; write in Taller's own detached worktree --

def _commit_in_worktree(entry: Project, payload: Mapping[str, bytes],
                        message: str) -> SyncState:
    """Commit on a detached head, then advance `main` by compare-and-swap.

    Nobody has `main` checked out, so moving the ref desynchronises no one. The
    worktree is Taller's alone, so resetting it discards nothing of anyone's.
    """
    repo = Path(entry["path"])
    worktree = ensure_main_worktree(entry)
    _git(worktree, "checkout", "--quiet", "--detach", "--force", MAIN_BRANCH)
    # Read `main` HERE, at the point the work is based on it, and use exactly this
    # value as the compare-and-swap's expected old value. Re-reading it just before
    # the swap would compare against whatever `main` had become by then - so an
    # owner commit made mid-write would pass the check and be overwritten.
    start = _rev(repo, f"refs/heads/{MAIN_BRANCH}")

    has_remote = _has_remote(worktree)
    if has_remote:
        _integrate_remote(worktree, payload)

    for relative, data in payload.items():
        locking.atomic_write(worktree / relative, data)
    if payload:
        _git(worktree, "add", "--", *payload)
    if _anything_staged(worktree):
        _git(worktree, "commit", "--quiet", "-m", message)

    new = _rev(worktree, "HEAD")
    if new != start and not _ok(
        repo, "update-ref", f"refs/heads/{MAIN_BRANCH}", new, start
    ):
        # `main` moved since `start` - an owner who checked it out and committed
        # mid-write, say. Recording `pending` and retrying later loses nothing;
        # overwriting their commit would.
        return SYNC_PENDING

    if not has_remote:
        return SYNC_LOCAL
    if _push(worktree, "HEAD"):
        return SYNC_OK
    # The remote moved between the fetch and the push. Rebase and retry once.
    _git(worktree, "fetch", "--quiet", REMOTE, check=False)
    if _rebase_onto_remote(worktree, payload):
        rebased = _rev(worktree, "HEAD")
        if (_ok(repo, "update-ref", f"refs/heads/{MAIN_BRANCH}", rebased, new)
                and _push(worktree, "HEAD")):
            return SYNC_OK
    return SYNC_PENDING


# --- path 2: the owner is on main; write into their checkout, only our paths --

def _commit_in_owner_checkout(repo: Path, payload: Mapping[str, bytes],
                              message: str) -> SyncState:
    """Commit the named paths only, leaving everything else of the owner's alone.

    `git commit --only` makes a commit containing exactly the listed paths, so the
    owner's other staged and unstaged work stays exactly as it was. Their index
    records the change, which is what stops their next commit deleting it.

    Never rewrites their branch: no rebase, no merge. A moved remote leaves the
    commit local and the state `pending`.
    """
    in_progress = _operation_in_progress(repo)
    if in_progress:
        raise GitError(
            f"{repo} is in the middle of a {in_progress}. Taller will not commit "
            f"into it until that is finished, because a commit now would land "
            f"inside your {in_progress} rather than beside it."
        )
    dirty = [relative for relative in payload if _has_local_changes(repo, relative)]
    if dirty:
        raise GitError(
            f"You have uncommitted changes to {', '.join(sorted(dirty))}, which "
            f"Taller needs to write. It will not overwrite them. Commit or discard "
            f"those changes, then retry."
        )

    for relative, data in payload.items():
        locking.atomic_write(repo / relative, data)
    if payload:
        _git(repo, "add", "--", *payload)
    if payload and _any_path_staged(repo, payload):
        _git(repo, "commit", "--quiet", "--only", "-m", message, "--", *payload)

    if not _has_remote(repo):
        return SYNC_LOCAL
    if not _ok(repo, "fetch", "--quiet", REMOTE):
        return SYNC_PENDING
    if _remote_main_exists(repo) and not _ok(
        repo, "merge-base", "--is-ancestor", f"{REMOTE}/{MAIN_BRANCH}", "HEAD"
    ):
        # The remote has commits `main` lacks. Integrating them would rewrite or
        # merge the owner's branch under them, which is not Taller's to do.
        return SYNC_PENDING
    return SYNC_OK if _push(repo, MAIN_BRANCH) else SYNC_PENDING


# --- helpers for the two paths ------------------------------------------------

def _current_branch(repo: Path) -> str | None:
    """The branch the owner's checkout is on, or None when detached."""
    result = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if result.returncode != 0:
        return None                       # detached
    return result.stdout.strip() or None


def _rev(cwd: Path, ref: str) -> str:
    return _git(cwd, "rev-parse", "--verify", ref).stdout.strip()


def _operation_in_progress(repo: Path) -> str | None:
    """A merge, rebase or cherry-pick the owner has not finished."""
    git_dir = Path(_git(repo, "rev-parse", "--git-dir").stdout.strip())
    if not git_dir.is_absolute():
        git_dir = repo / git_dir
    for marker, label in (
        ("MERGE_HEAD", "merge"),
        ("rebase-merge", "rebase"),
        ("rebase-apply", "rebase"),
        ("CHERRY_PICK_HEAD", "cherry-pick"),
        ("REVERT_HEAD", "revert"),
    ):
        if (git_dir / marker).exists():
            return label
    return None


def _has_local_changes(repo: Path, relative: str) -> bool:
    """Staged or unstaged changes to one path, relative to HEAD."""
    out = _git(repo, "status", "--porcelain", "--", relative, check=False)
    return bool(out.stdout.strip())


def _any_path_staged(repo: Path, payload: Mapping[str, bytes]) -> bool:
    """Whether any of our paths differs from HEAD in the index.

    Checked because a re-render that produced identical bytes stages nothing, and
    `commit --only` with nothing to commit fails. An unchanged snapshot is a
    normal outcome of `taller resolve`.
    """
    return not _ok(repo, "diff", "--cached", "--quiet", "--", *payload)


def _relative(raw: str | Path) -> str:
    """A project-relative POSIX path, or a raise. Never touches the filesystem."""
    text = str(raw).replace("\\", "/").strip()
    drive_prefixed = len(text) > 1 and text[1] == ":"
    if not text or text.startswith("/") or drive_prefixed:
        raise GitError(
            f"{raw!r} must be relative to the project root. An absolute path would "
            f"escape the `{MAIN_BRANCH}` worktree entirely."
        )
    parts = PurePosixPath(text).parts
    if not parts or ".." in parts:
        raise GitError(f"{raw!r} is not a usable project-relative path.")
    return "/".join(parts)


def _lf_bytes(data: bytes | str) -> bytes:
    """LF, whatever the platform. Spec 4.6's tamper check compares bytes, so a
    CRLF that reached the index would make a clean checkout report
    `constitution.resolved-snapshot-modified` at BLOCKER."""
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    return raw.replace(b"\r\n", b"\n")


def _assert_allowed(payload: Mapping[str, bytes], entry: Project) -> None:
    """Spec 7.2's list is a guarantee, not a convention.

    The brand tokens path is looked up only when something is not already on the
    fixed list, so the common write — a ticket file, or one of the three generated
    files — needs no hub read at all.
    """
    unknown = [relative for relative in payload if not _on_fixed_list(relative)]
    if not unknown:
        return
    tokens = brand_tokens_path(entry)
    for relative in unknown:
        if relative == tokens:
            continue
        raise GitError(
            f"{relative!r} is not a `{MAIN_BRANCH}`-side path. "
            f"gitio.commit_to_main() carries the owner's admin bypass on a "
            f"protected branch and may write only {ALLOWED_DESCRIPTION} "
            f"(spec 7.2). Anything else is a programming error, not a runtime "
            f"condition."
        )


def _on_fixed_list(relative: str) -> bool:
    if relative in FIXED_ALLOWED:
        return True
    parts = relative.split("/")
    if len(parts) < 4 or parts[0] != TALLER_DIR or parts[1] != WORK_DIR:
        return False
    tail = parts[3:]
    if len(tail) == 1 and tail[0] in TICKET_FILES:
        return True
    return tail[0] == REJECTED_DIR and len(tail) >= 2


# --- the remote ---------------------------------------------------------------

def _has_remote(worktree: Path) -> bool:
    """No-remote mode is the greenfield default, not an error path (spec 7.3).

    `project new` creates a remote only if asked and the hub is local-only by
    default, so most projects never have one. `git fetch origin` and `git push`
    both exit 128 without it, which is why this is checked rather than attempted.
    """
    return REMOTE in _git(worktree, "remote", check=False).stdout.split()


def _remote_main_exists(worktree: Path) -> bool:
    return _ok(worktree, "rev-parse", "--verify", "--quiet",
               f"refs/remotes/{REMOTE}/{MAIN_BRANCH}")


def _integrate_remote(worktree: Path, payload: Mapping[str, bytes]) -> None:
    """Fetch, then fast-forward onto `origin/main`, rebasing if it is refused.

    Best effort throughout: an unreachable remote is `sync: pending`, which the
    push at the end of `commit_to_main()` will discover on its own.
    """
    if not _ok(worktree, "fetch", "--quiet", REMOTE):
        return
    if not _remote_main_exists(worktree):
        return                              # an empty remote; nothing to catch up to
    if _ok(worktree, "merge", "--ff-only", "--quiet", f"{REMOTE}/{MAIN_BRANCH}"):
        return
    _rebase_onto_remote(worktree, payload)


def _rebase_onto_remote(worktree: Path, payload: Mapping[str, bytes]) -> bool:
    """Replay the local `main`-side commits onto `origin/main`. True on success.

    All but one of spec 7.2's paths are under `.taller/`, so they cannot conflict
    with application code. The exception is `paths.brand_tokens`, which sits inside
    the application's own tree. It is generated, so a conflict there is resolved by
    discarding both sides and writing the bytes this call is about to commit anyway
    — spec 4.6's rule that no generated file is ever merged.

    A conflict in anything else is left alone: aborting and reporting `pending`
    loses no transition, whereas resolving the owner's application code on their
    behalf would.
    """
    if not _remote_main_exists(worktree):
        return False
    result = _git(worktree, "rebase", f"{REMOTE}/{MAIN_BRANCH}", check=False)
    for _ in range(MAX_REBASE_STEPS):
        if result.returncode == 0:
            return True
        conflicted = _conflicted(worktree)
        if not conflicted or not set(conflicted) <= set(payload):
            break
        for relative in conflicted:
            locking.atomic_write(worktree / relative, payload[relative])
            _git(worktree, "add", "--", relative)
        result = _git(worktree, "rebase", "--continue", check=False)
    _git(worktree, "rebase", "--abort", check=False)
    return False


def _conflicted(worktree: Path) -> list[str]:
    out = _git(worktree, "diff", "--name-only", "--diff-filter=U", check=False)
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def _anything_staged(worktree: Path) -> bool:
    """`diff --cached --quiet` exits non-zero when the index differs from HEAD.

    Checked rather than assumed: a re-render that produced identical bytes would
    otherwise fail the commit, and an unchanged snapshot is a normal outcome of
    `taller resolve`.
    """
    return not _ok(worktree, "diff", "--cached", "--quiet")


def _push(cwd: Path, source: str) -> bool:
    """Push `source` to the remote's `main`. A refspec, so a detached head works."""
    return _ok(cwd, "push", "--quiet", REMOTE, f"{source}:refs/heads/{MAIN_BRANCH}")
