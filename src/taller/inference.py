"""The only module that spawns the `claude` CLI.

Everything else asks for a dispatch and receives a result, so how inference is
performed is a single decision in a single place (spec 3.6). That is also the
only reason replacing the subprocess with an embedded Agent SDK client would be
a swap rather than a rewrite — though doing so would forfeit subscription
billing (spec 5.2) and is not expected.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config, paths
from .errors import InferenceError

# Tools that can modify a file. `forbidden` globs expand across all of them,
# because --disallowedTools matches tools, not paths (spec 3.6.1).
WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")

BARE_BASH = "Bash"

# Generous, but finite. locking._reap_if_stale only reclaims a lock whose process
# is GONE, so a live-but-wedged dispatch is invisible to it and would hold its
# concurrency slot until every other process timed out waiting.
DISPATCH_TIMEOUT = 1800.0

READ_ONLY = ["Read", "Glob", "Grep"]

# Spec 3.6.1's per-role table, verbatim. It lives here rather than at each call
# site because spec 15.1 asserts on the generated argument list and cannot be
# written against "the specifiers it needs".
#
# Two properties worth noting:
#   * A read-only role has NO forbidden list. It is granted no write-capable
#     tool, so there is nothing to forbid.
#   * `implementer` keeps bare Bash and has an empty forbidden list; it must be
#     able to run arbitrary commands to check its own work, and is bounded by
#     --add-dir alone. The no-test-file rule is the FIXER's, because "make a
#     failing test pass by editing the test" is a fix round's temptation.
ROLE_TOOLS: dict[str, list[str]] = {
    "chief": READ_ONLY + ["Bash(git status*)", "Bash(git log*)", "Bash(git diff*)"],
    "explorer": READ_ONLY,
    "scribe": ["Read"],
    "summariser": ["Read"],
    "gate_security": READ_ONLY,
    "gate_quality": READ_ONLY,
    "gate_ux": READ_ONLY,
    "architect": READ_ONLY + ["Write", "Edit"],
    "implementer": READ_ONLY + ["Write", "Edit", "NotebookEdit", BARE_BASH],
    "fixer": READ_ONLY + [
        "Write", "Edit", "NotebookEdit",
        "Bash(pytest*)", "Bash(python -m pytest*)",
        "Bash(git diff*)", "Bash(git status*)",
    ],
}

# Only the fixer restricts paths, and only the fixer therefore loses bare Bash.
FIXER_FORBIDDEN = ["**/test_*.py", "**/*_test.py"]


def role_tools(role: str) -> list[str]:
    """The allowlist for a role. Raises rather than silently granting nothing."""
    try:
        return list(ROLE_TOOLS[role])
    except KeyError as exc:
        raise InferenceError(f"No tool allowlist defined for role {role!r}.") from exc


def role_forbidden(role: str, tests_dir: str) -> list[str]:
    """The forbidden globs for a role. Empty for every role but the fixer.

    `tests_dir` has no default on purpose. A default of "tests" silently protected
    the wrong directory in a project whose tests live in `test/` or `spec/`, which
    voids spec 9.7's guarantee with no error at all. Omitting it is a TypeError.
    """
    if role != "fixer":
        return []
    return [f"{tests_dir}/**", *FIXER_FORBIDDEN]


def _default_forbidden(dispatch: "Dispatch") -> list[str]:
    """The role's forbidden globs, taking tests_dir from the RuleSet when there is
    one. In bootstrap mode there is no project, and no role that restricts paths."""
    if dispatch.role != "fixer":
        return []
    ruleset = dispatch.ruleset or {}
    tests_dir = (ruleset.get("paths") or {}).get("tests_dir")
    if not tests_dir:
        raise InferenceError(
            "A fixer dispatch needs paths.tests_dir from its RuleSet to know which "
            "directory to protect. Pass a resolved RuleSet, or set `forbidden` "
            "explicitly."
        )
    return role_forbidden(dispatch.role, tests_dir)


@dataclass
class UsageRecord:
    """Named for the four fields `weights` and `pricing` are keyed by (spec 5.1),
    so the rename from the CLI's field names happens once, here."""
    model: str
    input: int = 0
    cache_write: int = 0
    cache_read: int = 0
    output: int = 0


@dataclass
class Dispatch:
    role: str
    prompt: str
    config: config.HubConfig
    ruleset: dict[str, Any] | None = None
    model: str | None = None
    effort: str | None = None
    system: str | None = None
    resume: str | None = None
    cwd: Path | str | None = None       # None -> the bootstrap scratch dir
    writable: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    agents: dict[str, Any] | None = None
    schema: dict[str, Any] | None = None
    unattended: bool = True
    # Injected by the caller from cli_probe, never probed here: probing inside
    # infer() spawned `claude --help` on the first dispatch of every process,
    # which made a "never retries" assertion order-dependent.
    supports_permission_prompts: bool = False
    # Environment variables removed for this one dispatch. `taller doctor` uses it
    # to prove subscription auth works with no API key in sight (spec 15.4).
    unset_env: tuple[str, ...] = ()
    # Seconds before the dispatch is abandoned. Real work gets half an hour; a
    # health check that waits that long just looks frozen.
    timeout: float = DISPATCH_TIMEOUT


@dataclass
class Result:
    ok: bool
    value: Any = None
    error: str | None = None
    session_id: str = ""
    usage: list[UsageRecord] = field(default_factory=list)
    cost_usd: float | None = None       # CUMULATIVE when resuming (spec 7.5)


def infer(dispatch: Dispatch, executable: str = "claude") -> Result:
    """Perform one act of inference. Never retries — that is the caller's policy.

    Two classes of failure, deliberately different:
      * A *contract violation* by an internal caller — a role holding both bare
        Bash and forbidden paths, or a dispatch trying to write the main worktree
        — RAISES InferenceError. These are bugs in Taller, not runtime conditions,
        and folding them into a Result would hide the guarantee spec 9.7 rests on.
      * A *runtime* failure — bad exit, bad JSON, schema mismatch, missing binary
        — returns ok: false with a distinct reason, for the caller's retry policy.
    """
    # Fill the role's allowlist and forbidden globs when a caller omitted them.
    # Leaving them empty was fail-open twice over: an empty `tools` means no
    # --allowedTools at all, so the dispatch runs with the CLI's full default tool
    # set under --permission-mode dontAsk; and a fixer given `tools` but not
    # `forbidden` gets Write/Edit with no --disallowedTools, voiding the one
    # guarantee spec 9.7 rests on. The table is right here, so use it.
    if not dispatch.tools:
        dispatch.tools = role_tools(dispatch.role)
    if not dispatch.forbidden:
        dispatch.forbidden = _default_forbidden(dispatch)

    argv_tail, cwd = _build(dispatch, executable)   # may raise: see above

    # Resolve to an absolute path BEFORE spawning. On Windows, CreateProcess
    # appends only .exe to an extensionless name, so spawning bare "claude" skips
    # a claude.cmd earlier on PATH and runs the real claude.exe instead — which
    # would make the whole test suite issue real, billed dispatches.
    resolved = shutil.which(executable)
    if resolved is None:
        return Result(
            ok=False,
            error=f"The `{executable}` CLI is not on PATH. Taller performs every "
                  f"act of inference through it.",
        )
    argv = [resolved, *argv_tail]

    from .errors import LockTimeout
    try:
        slot = _slot(dispatch)
        slot.__enter__()
    except LockTimeout as exc:
        # Neither a Taller bug nor a CLI failure: the account's own concurrency
        # ceiling. The documented contract is a Result, so a LockTimeout must not
        # escape infer().
        return Result(ok=False, error=str(exc))
    try:
        try:
            completed = _run_bounded(
                argv,
                input=_prompt(dispatch),
                # UTF-8 on both directions, explicitly. Without it Python uses the
                # locale encoding - cp1252 on Windows - and two things break
                # silently: a prompt containing any character outside cp1252 (an
                # arrow, an em dash) raises UnicodeEncodeError out of infer(), and
                # a UTF-8 answer decodes to mojibake that still parses as JSON, so
                # "reunion" comes back with its accent replaced by two characters
                # and nothing reports an error. Verified both ways on this machine.
                encoding="utf-8",
                errors="replace",
                cwd=str(cwd),
                timeout=dispatch.timeout,
                env=({k: v for k, v in os.environ.items() if k not in dispatch.unset_env}
                     if dispatch.unset_env else None),
            )
        except subprocess.TimeoutExpired:
            return Result(
                ok=False,
                error=f"The dispatch produced no result within "
                      f"{dispatch.timeout:g}s and was abandoned. A wedged CLI would "
                      f"otherwise hold its concurrency slot indefinitely.",
            )
    finally:
        slot.__exit__(None, None, None)

    if completed.returncode == 143:
        return Result(
            ok=False,
            error="The dispatch was interrupted (exit 143); the turn is unfinished "
                  "and no result was recorded.",
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        # A failed turn still answers in JSON, and its `result` is the one line
        # that says what happened ("Not logged in"). Cut at 500 characters, the
        # raw JSON showed only usage counters - found in first real use.
        try:
            payload = json.loads(completed.stdout)
            if isinstance(payload, dict) and payload.get("result"):
                detail = str(payload["result"])
        except (json.JSONDecodeError, TypeError):
            pass
        detail = detail[:500]
        return Result(ok=False, error=f"`{executable}` failed with exit "
                                      f"{completed.returncode}: {detail}")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return Result(ok=False, error=f"`{executable}` returned output that is not "
                                      f"JSON: {exc}")
    if not isinstance(payload, dict):
        return Result(
            ok=False,
            error=f"`{executable}` returned JSON that is not an object "
                  f"({type(payload).__name__}); every field lookup below assumes one.",
        )

    if payload.get("is_error"):
        # A failed turn was still billed, so its usage must be recorded (spec 7.5).
        return Result(ok=False, error=str(payload.get("result", "unknown error")),
                      session_id=payload.get("session_id", ""),
                      usage=_usage(payload),
                      cost_usd=payload.get("total_cost_usd"))

    if dispatch.schema is not None and "structured_output" not in payload:
        return Result(
            ok=False,
            error="A schema was requested but the answer carried no "
                  "`structured_output`; the model did not satisfy it.",
            session_id=payload.get("session_id", ""),
            usage=_usage(payload),
            cost_usd=payload.get("total_cost_usd"),
        )

    value = payload.get("structured_output", payload.get("result"))
    return Result(
        ok=True,
        value=value,
        session_id=payload.get("session_id", ""),
        usage=_usage(payload),
        cost_usd=payload.get("total_cost_usd"),
    )


def _run_bounded(argv: list[str], *, input: str, encoding: str, errors: str, cwd: str,
                 timeout: float, env: dict[str, str] | None) -> subprocess.CompletedProcess:
    """`subprocess.run`, except that a timeout ends the whole process tree.

    `claude` starts children of its own - the MCP servers of every plugin the
    owner has installed. `subprocess.run` kills only the direct child on timeout
    and then waits for its output pipes, which those orphans can hold open, so a
    wedged dispatch could outlive its own timeout. Found when `taller doctor`
    sat waiting on a dispatch that never answered.
    """
    popen_extra: dict[str, Any] = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
        else {"start_new_session": True})
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding=encoding,
                               errors=errors, cwd=cwd, env=env, **popen_extra)
    try:
        stdout, stderr = process.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass                                # the pipes are abandoned, not awaited
        raise
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def _kill_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                       capture_output=True)
    else:
        import signal
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        process.kill()


def _build(dispatch: Dispatch, executable: str) -> tuple[list[str], Path]:
    cfg = dispatch.ruleset or dispatch.config

    model = dispatch.model or config.resolve_model(dispatch.role, cfg)
    effort = dispatch.effort or config.resolve_effort(dispatch.role, cfg)

    # Spec 3.6.1: a shell circumvents a --disallowedTools specifier, so a role
    # with forbidden paths may not hold bare Bash.
    if dispatch.forbidden and BARE_BASH in dispatch.tools:
        raise InferenceError(
            f"Role {dispatch.role!r} has forbidden paths but its allowlist contains "
            f"bare Bash. A shell circumvents --disallowedTools specifiers, so this "
            f"combination would make the restriction cosmetic. Allowlist the "
            f"specific Bash(...) specifiers it needs instead."
        )

    # Only the bootstrap scratch directory is created here. Creating an arbitrary
    # cwd would turn a stale or mistyped worktree path into an empty directory, and
    # a dispatch would then run against nothing and report success.
    if dispatch.cwd is None:
        cwd = paths.scratch_cwd()
        cwd.mkdir(parents=True, exist_ok=True)
    else:
        cwd = Path(dispatch.cwd)
        if not cwd.is_dir():
            raise InferenceError(
                f"{cwd} is not a directory. A dispatch's cwd must already exist; "
                f"only the bootstrap scratch directory is created on demand."
            )

    # argv WITHOUT the executable; infer() prepends the resolved absolute path.
    argv = ["-p", "--output-format", "json", "--model", model, "--effort", effort]

    if dispatch.resume:
        argv += ["--resume", dispatch.resume]
    if dispatch.tools:
        argv += ["--allowedTools", ",".join(dispatch.tools)]
    if dispatch.forbidden:
        argv += ["--disallowedTools", ",".join(_expand_forbidden(dispatch.forbidden))]
    worktrees_root = (paths.run_dir() / "worktrees").resolve()
    for directory in dispatch.writable:
        candidate = Path(directory).resolve()
        # Compare against the real location, not a name suffix: a legitimate
        # checkout called `foo-main` must not be rejected.
        if candidate == worktrees_root or worktrees_root in candidate.parents:
            raise InferenceError(
                f"{candidate} is inside the main-worktree root and must never be "
                f"writable by a dispatch; gitio.commit_to_main() is its only "
                f"writer (spec 3.6.1)."
            )
        argv += ["--add-dir", str(candidate)]
    if dispatch.schema is not None:
        argv += ["--json-schema", json.dumps(dispatch.schema)]
    if dispatch.agents is not None:
        argv += ["--agents", json.dumps(dispatch.agents)]
    if dispatch.unattended:
        argv += ["--permission-mode", "dontAsk"]
        if dispatch.supports_permission_prompts:
            argv += ["--permission-prompts", "none"]

    # The brief is always the role's definition, then its slices, then any
    # `system` the caller adds - never `system` alone, or a dispatch would not
    # know which role it is. It goes LAST: it is the one multi-line argument, and
    # a Windows .cmd shim (the test stub) drops everything after a line break,
    # so every flag that matters must come before it. The real binary is spawned
    # without a shell and receives all of it either way.
    argv += ["--append-system-prompt", _brief(dispatch)]

    # --bare is deliberately absent: it never reads OAuth credentials, so it
    # would silently require an API key (spec 3.6.2).
    return argv, cwd


def _brief(dispatch: Dispatch) -> str:
    """The system prompt: the role's definition, then any `system` the caller adds.

    The definition comes first, so the brief's first line is `ROLE: <role>`. It
    is short on purpose: it travels on the command line, which Windows caps at
    32,767 characters (8,191 through cmd.exe). The project's rules - which can be
    far longer - travel in the prompt instead (`_rules`).
    """
    from . import roles                   # roles imports this module

    parts = [roles.definition(dispatch.role).strip()]
    if dispatch.system:
        parts.append(dispatch.system)
    return "\n\n".join(p.strip() for p in parts if p and p.strip()) + "\n"


def _rules(dispatch: Dispatch) -> str:
    """Only THIS role's slices of the constitution (3.6.0), for the head of the prompt.

    An earlier version concatenated every slice in the RuleSet, so a UX gate was
    briefed with the security and product slices too - wasteful, confusing, and it
    quietly gave up the context saving the whole design is built on.
    """
    slices = (dispatch.ruleset or {}).get("slices") or {}
    parts = []
    for name in role_slices(dispatch.role):
        resolved = slices.get(name)
        if not resolved:
            continue                    # a slice this project does not provide
        parts.append(resolved["text"] if isinstance(resolved, dict) else str(resolved))
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _prompt(dispatch: Dispatch) -> str:
    """What goes to stdin: the project's rules for this role, then the task.

    Stdin has no length limit, which is why the rules are here and not in the
    system prompt (see `_brief`).
    """
    rules = _rules(dispatch)
    if not rules:
        return dispatch.prompt
    return f"# The project's rules\n\n{rules}\n\n# The task\n\n{dispatch.prompt}"


def _expand_forbidden(globs: list[str]) -> list[str]:
    return [f"{tool}({glob})" for glob in globs for tool in WRITE_TOOLS]


def _usage(payload: dict[str, Any]) -> list[UsageRecord]:
    per_model = payload.get("modelUsage") or {}
    if per_model:
        return [
            UsageRecord(
                model=model,
                input=int(u.get("inputTokens") or 0),
                cache_write=int(u.get("cacheCreationInputTokens") or 0),
                cache_read=int(u.get("cacheReadInputTokens") or 0),
                output=int(u.get("outputTokens") or 0),
            )
            for model, u in per_model.items()
        ]
    usage = payload.get("usage") or {}
    if not usage:
        return []
    return [UsageRecord(
        model=payload.get("model", "unknown"),
        input=int(usage.get("input_tokens") or 0),
        cache_write=int(usage.get("cache_creation_input_tokens") or 0),
        cache_read=int(usage.get("cache_read_input_tokens") or 0),
        output=int(usage.get("output_tokens") or 0),
    )]


@contextlib.contextmanager
def _slot(dispatch: Dispatch):  # noqa: C901
    """A counted semaphore across processes.

    The limit being protected is a per-account usage window (spec 5.2), and the
    CLI, the cockpit and a Claude Code session can all dispatch at once — so a
    per-process counter would bound nothing that matters.

    The slot is acquired BEFORE the yield and released in a finally. An earlier
    draft yielded inside a `try/except Exception` inside the acquisition loop,
    which caught the wrapped body's own exception, retried the loop, and surfaced
    as `RuntimeError: generator didn't stop after throw()` with the real cause
    gone — while abandoning the generator still holding the lock.
    """
    cfg = dispatch.ruleset or dispatch.config
    concurrency = cfg.get("concurrency", {})
    thinker = cfg.get("model_aliases", {}).get("thinker")
    model = dispatch.model or config.resolve_model(dispatch.role, cfg)

    # Two pools, matching spec 5.1's two keys. One shared namespace would make an
    # Opus dispatch queue behind an unrelated Sonnet one, and would apply the gate
    # limit to the chief, the implementer and the scribe as well.
    if model == thinker:
        pool, limit = "thinker", concurrency.get("max_parallel_thinker", 1)
    else:
        pool, limit = "worker", concurrency.get("max_parallel_gates", 3)
    limit = max(1, int(limit))

    pool_dir = paths.dispatch_slots() / pool
    pool_dir.mkdir(parents=True, exist_ok=True)

    acquired = _acquire_slot(pool_dir, limit)
    try:
        yield                       # exactly one yield, outside any except
    finally:
        acquired.__exit__(None, None, None)


def _acquire_slot(pool_dir: Path, limit: int, timeout: float = 300.0):
    """Take the first free slot, polling every slot until one frees or we time out.

    Returns the entered context manager so the caller can release it in a
    `finally`. Only slot acquisition is guarded here; the body is not.

    An earlier version parked a queued dispatch on slot-0 alone. With three slots
    and five waiters, four of them piled onto slot-0 while slots 1 and 2 sat idle,
    so queued work serialised toward one-at-a-time and a waiter could sleep out its
    whole timeout beside free capacity.
    """
    from . import locking
    from .errors import LockTimeout

    # Waiting is futile when THIS thread already holds a slot in this pool: the
    # thread that would release it is the one blocked here. Fail fast instead of
    # polling for the full timeout.
    if any(locking.held(pool_dir / f"slot-{i}.lock") for i in range(limit)):
        raise LockTimeout(
            f"This thread already holds a slot in {pool_dir.name}. A dispatch "
            f"cannot nest inside another on one thread."
        )

    deadline = time.monotonic() + timeout
    while True:
        for index in range(limit):
            candidate = locking.file_lock(
                pool_dir / f"slot-{index}.lock", timeout=0.05, reentrant=False
            )
            try:
                candidate.__enter__()
            except LockTimeout:
                continue                # that slot is busy; try the next
            return candidate
        if time.monotonic() >= deadline:
            raise LockTimeout(
                f"No dispatch slot became free in {pool_dir.name} within "
                f"{timeout:g}s ({limit} slot(s))."
            )
        time.sleep(0.05)


# Spec 3.6.0's role -> slices map. Defined here because `_brief` is the only
# consumer. A gate briefed with three slices instead of nine is the difference
# between the design's token claim and a slogan.
ROLE_SLICES: dict[str, tuple[str, ...]] = {
    "chief": ("stack", "never", "overrides"),
    "scribe": ("product",),
    "explorer": ("architecture",),
    "architect": ("product", "architecture", "conventions", "never", "overrides"),
    "implementer": ("stack", "architecture", "conventions", "brand", "ux",
                    "never", "overrides"),
    "fixer": ("stack", "architecture", "conventions", "brand", "ux",
              "never", "overrides"),
    "gate_security": ("security", "never", "overrides"),
    "gate_quality": ("conventions", "architecture", "never", "overrides"),
    "gate_ux": ("ux", "brand", "conventions", "never", "overrides"),
    "summariser": ("product",),
}


def role_slices(role: str) -> tuple[str, ...]:
    """The slice names that brief a role. Raises rather than briefing with nothing."""
    try:
        return ROLE_SLICES[role]
    except KeyError as exc:
        raise InferenceError(f"No slice set defined for role {role!r}.") from exc
