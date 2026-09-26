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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config, paths
from .errors import InferenceError

# Tools that can modify a file. `forbidden` globs expand across all of them,
# because --disallowedTools matches tools, not paths (spec 3.6.1).
WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")

BARE_BASH = "Bash"

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


def role_forbidden(role: str, tests_dir: str = "tests") -> list[str]:
    """The forbidden globs for a role. Empty for every role but the fixer."""
    if role != "fixer":
        return []
    return [f"{tests_dir}/**", *FIXER_FORBIDDEN]


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

    with _slot(dispatch):
        completed = subprocess.run(
            argv, input=dispatch.prompt, capture_output=True, text=True, cwd=str(cwd)
        )

    if completed.returncode == 143:
        return Result(
            ok=False,
            error="The dispatch was interrupted (exit 143); the turn is unfinished "
                  "and no result was recorded.",
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[:500]
        return Result(ok=False, error=f"`{executable}` failed with exit "
                                      f"{completed.returncode}: {detail}")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return Result(ok=False, error=f"`{executable}` returned output that is not "
                                      f"JSON: {exc}")

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

    cwd = Path(dispatch.cwd) if dispatch.cwd else paths.scratch_cwd()
    cwd.mkdir(parents=True, exist_ok=True)

    # argv WITHOUT the executable; infer() prepends the resolved absolute path.
    argv = ["-p", "--output-format", "json", "--model", model, "--effort", effort]

    # `system` replaces the slice briefing, never the effort. An earlier draft
    # computed effort and then discarded it whenever a caller supplied `system`,
    # which is exactly the bootstrap case.
    system = dispatch.system or _brief(dispatch)
    if system:
        argv += ["--append-system-prompt", system]
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

    # --bare is deliberately absent: it never reads OAuth credentials, so it
    # would silently require an API key (spec 3.6.2).
    return argv, cwd


def _brief(dispatch: Dispatch) -> str:
    """The role's slices, concatenated. Effort travels as --effort, not as prose."""
    slices = (dispatch.ruleset or {}).get("slices") or {}
    parts = [
        resolved["text"] if isinstance(resolved, dict) else str(resolved)
        for resolved in slices.values()
    ]
    return "\n\n".join(p for p in parts if p)


def _expand_forbidden(globs: list[str]) -> list[str]:
    return [f"{tool}({glob})" for glob in globs for tool in WRITE_TOOLS]


def _usage(payload: dict[str, Any]) -> list[UsageRecord]:
    per_model = payload.get("modelUsage") or {}
    if per_model:
        return [
            UsageRecord(
                model=model,
                input=int(u.get("inputTokens", 0)),
                cache_write=int(u.get("cacheCreationInputTokens", 0)),
                cache_read=int(u.get("cacheReadInputTokens", 0)),
                output=int(u.get("outputTokens", 0)),
            )
            for model, u in per_model.items()
        ]
    usage = payload.get("usage") or {}
    if not usage:
        return []
    return [UsageRecord(
        model=payload.get("model", "unknown"),
        input=int(usage.get("input_tokens", 0)),
        cache_write=int(usage.get("cache_creation_input_tokens", 0)),
        cache_read=int(usage.get("cache_read_input_tokens", 0)),
        output=int(usage.get("output_tokens", 0)),
    )]


@contextlib.contextmanager
def _slot(dispatch: Dispatch):
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
    from . import locking

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


def _acquire_slot(pool_dir: Path, limit: int):
    """Take the first free slot, or wait on slot 0 when all are busy.

    Returns the entered context manager so the caller can release it in a
    `finally`. Only slot acquisition is guarded here; the body is not.
    """
    from . import locking
    from .errors import LockTimeout

    for index in range(limit):
        candidate = locking.file_lock(
            pool_dir / f"slot-{index}.lock", timeout=0.05, reentrant=False
        )
        try:
            candidate.__enter__()
        except LockTimeout:
            continue                # that slot is busy; try the next
        return candidate

    waiting = locking.file_lock(pool_dir / "slot-0.lock", timeout=300, reentrant=False)
    waiting.__enter__()
    return waiting
