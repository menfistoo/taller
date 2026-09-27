import json
from pathlib import Path

import pytest

from taller import config, inference, paths
from taller.errors import InferenceError


def _bootstrap_dispatch(**over):
    """A dispatch with no project — the first thing Phase A exercises (spec 3.6)."""
    role = over.get("role", "scribe")
    base = dict(
        role=role,
        prompt="hello",
        ruleset=None,
        config=config.load_hub_config(),
        cwd=None,                                   # -> scratch
        writable=[],
        tools=inference.role_tools(role),           # the spec 3.6.1 table
        forbidden=inference.role_forbidden(role, "tests"),
        agents=None,
        schema=None,
        unattended=True,
        supports_permission_prompts=False,          # injected, never probed
    )
    base.update(over)
    return inference.Dispatch(**base)


def test_bootstrap_dispatch_needs_no_ruleset(tmp_home, stub_claude):
    result = inference.infer(_bootstrap_dispatch())
    assert result.ok
    assert result.session_id == "11111111-2222-3333-4444-555555555555"


def test_bootstrap_uses_the_scratch_cwd_which_has_no_briefing(tmp_home, stub_claude):
    inference.infer(_bootstrap_dispatch())
    scratch = paths.scratch_cwd()
    assert scratch.is_dir()
    # Spec 3.6: no CLAUDE.md and no .claude/, so a bootstrap dispatch cannot
    # inherit an arbitrary repository's briefing or hooks.
    assert not (scratch / "CLAUDE.md").exists()
    assert not (scratch / ".claude").exists()


def test_model_comes_from_the_role_via_the_alias(tmp_home, stub_claude):
    inference.infer(_bootstrap_dispatch(role="architect"))
    assert "--model opus" in stub_claude.flags()


def test_explicit_model_wins(tmp_home, stub_claude):
    inference.infer(_bootstrap_dispatch(model="haiku"))
    assert "--model haiku" in stub_claude.flags()


def test_bare_is_never_passed(tmp_home, stub_claude):
    # Spec 3.6.2: bare mode never reads OAuth credentials, so it would silently
    # break subscription billing.
    inference.infer(_bootstrap_dispatch())
    assert "--bare" not in stub_claude.last()


def test_session_is_captured_and_replayed(tmp_home, stub_claude):
    first = inference.infer(_bootstrap_dispatch())
    inference.infer(_bootstrap_dispatch(resume=first.session_id))
    assert "--resume" in stub_claude.last()
    assert first.session_id in stub_claude.last()
    # Never pre-generated (spec 3.6).
    assert "--session-id" not in stub_claude.last()


def test_forbidden_expands_to_tool_specifiers_not_paths(tmp_home, stub_claude):
    inference.infer(_bootstrap_dispatch(
        role="fixer", forbidden=["tests/**"], tools=["Read", "Write", "Edit"]
    ))
    flags = stub_claude.flags()
    # Spec 3.6.1: a bare path would match no tool and restrict nothing.
    assert "Write(tests/**)" in flags
    assert "Edit(tests/**)" in flags
    assert "NotebookEdit(tests/**)" in flags
    assert "--disallowedTools tests/**" not in flags


def test_the_role_table_never_gives_the_fixer_bare_bash(tmp_home):
    # The table is the source of truth, so assert on the table itself.
    assert "Bash" not in inference.role_tools("fixer")
    assert inference.role_forbidden("fixer", "tests")   # it does restrict paths
    assert any(t.startswith("Bash(") for t in inference.role_tools("fixer"))


def test_the_implementer_keeps_bare_bash_and_forbids_nothing(tmp_home):
    # It must run arbitrary commands to check its own work; --add-dir bounds it.
    assert "Bash" in inference.role_tools("implementer")
    assert inference.role_forbidden("implementer", "tests") == []


def test_read_only_roles_get_no_write_tools_and_no_forbidden_list(tmp_home):
    for role in ("explorer", "scribe", "summariser", "gate_security", "gate_ux"):
        tools = inference.role_tools(role)
        assert not {"Write", "Edit", "NotebookEdit"} & set(tools), role
        assert inference.role_forbidden(role, "tests") == [], role


def test_a_role_with_forbidden_paths_and_bare_bash_is_a_contract_violation(tmp_home, stub_claude):
    # A shell walks straight around a --disallowedTools specifier (spec 3.6.1).
    # This is a bug in the caller, so it RAISES rather than returning a Result.
    with pytest.raises(InferenceError, match="bare Bash"):
        inference.infer(_bootstrap_dispatch(
            role="fixer", forbidden=["tests/**"], tools=["Read", "Write", "Bash"]
        ))


def test_writing_the_main_worktree_is_a_contract_violation(tmp_home, stub_claude):
    # spec 15.1 requires this be asserted; gitio.commit_to_main() is the only
    # writer of the main-side files.
    forbidden_dir = paths.main_worktree("demo")
    forbidden_dir.mkdir(parents=True)
    with pytest.raises(InferenceError, match="main-worktree"):
        inference.infer(_bootstrap_dispatch(
            role="implementer", writable=[str(forbidden_dir)]
        ))


def test_a_project_directory_merely_named_foo_main_is_allowed(tmp_home, stub_claude, tmp_path):
    # A name-suffix check would have rejected a legitimate checkout.
    legit = tmp_path / "foo-main"
    legit.mkdir()
    result = inference.infer(_bootstrap_dispatch(
        role="implementer", cwd=legit, writable=[str(legit)]
    ))
    assert result.ok


def test_writable_becomes_add_dir(tmp_home, stub_claude, tmp_path):
    work = tmp_path / "wt"
    work.mkdir()
    inference.infer(_bootstrap_dispatch(role="implementer", cwd=work, writable=[str(work)]))
    assert f"--add-dir {work.resolve()}" in stub_claude.flags()


def test_effort_always_reaches_the_dispatch(tmp_home, stub_claude):
    # Native flag, verified present on claude 2.1.74.
    inference.infer(_bootstrap_dispatch(role="architect"))
    assert "--effort high" in stub_claude.flags()


def test_effort_survives_an_explicit_system_prompt(tmp_home, stub_claude):
    # The bootstrap case: `system` replaces the briefing, never the effort.
    inference.infer(_bootstrap_dispatch(role="architect", system="you are a planner"))
    flags = stub_claude.flags()
    assert "--effort high" in flags
    assert "you are a planner" in flags


def test_a_schema_mismatch_is_its_own_failure(tmp_home, stub_claude, monkeypatch):
    # spec 3.6.3 lists it among the failures that each need a distinct reason.
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", (
        '{"session_id":"s","is_error":false,"result":"prose, not structured",'
        '"usage":{"input_tokens":1,"cache_creation_input_tokens":0,'
        '"cache_read_input_tokens":0,"output_tokens":1}}'
    ))
    result = inference.infer(_bootstrap_dispatch(schema={"type": "object"}))
    assert not result.ok
    assert "structured_output" in result.error


def test_a_failed_turn_still_reports_its_usage(tmp_home, stub_claude, monkeypatch):
    # It was billed, so spend must see it (spec 7.5).
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", (
        '{"session_id":"s","is_error":true,"result":"refused",'
        '"usage":{"input_tokens":5,"cache_creation_input_tokens":0,'
        '"cache_read_input_tokens":0,"output_tokens":7}}'
    ))
    result = inference.infer(_bootstrap_dispatch())
    assert not result.ok
    assert result.usage and result.usage[0].output == 7


def test_a_nested_slot_cannot_exceed_the_cap(tmp_home):
    """One thread taking two slots from a one-slot pool must fail, not succeed."""
    from taller.errors import LockTimeout

    pool = paths.dispatch_slots() / "thinker"
    pool.mkdir(parents=True, exist_ok=True)
    outer = inference._acquire_slot(pool, limit=1)
    try:
        with pytest.raises(LockTimeout):
            inference._acquire_slot(pool, limit=1)
    finally:
        outer.__exit__(None, None, None)
    assert not list(pool.glob("*.lock")), "a slot leaked"


def test_the_body_exception_is_not_swallowed_by_the_slot(tmp_home, stub_claude, monkeypatch):
    """An earlier draft yielded inside a try/except in the acquisition loop, so a
    body failure surfaced as `generator didn't stop after throw()`."""
    def boom(*args, **kwargs):
        raise OSError("BODY BOOM")

    # The dispatch body: where the CLI is spawned and waited on.
    monkeypatch.setattr(inference, "_run_bounded", boom)
    with pytest.raises(OSError, match="BODY BOOM"):
        inference.infer(_bootstrap_dispatch())


def test_schema_becomes_json_schema(tmp_home, stub_claude, monkeypatch):
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", (
        '{"session_id":"s","is_error":false,'
        '"structured_output":{"verdict":"pass"},'
        '"usage":{"input_tokens":1,"cache_creation_input_tokens":0,'
        '"cache_read_input_tokens":0,"output_tokens":1}}'
    ))
    result = inference.infer(_bootstrap_dispatch(schema={"type": "object"}))
    assert "--json-schema" in stub_claude.flags()
    assert result.value == {"verdict": "pass"}


def test_unattended_sets_permission_mode(tmp_home, stub_claude):
    inference.infer(_bootstrap_dispatch(unattended=True))
    assert "--permission-mode dontAsk" in stub_claude.flags()


def test_usage_is_normalised_to_the_weight_field_names(tmp_home, stub_claude):
    result = inference.infer(_bootstrap_dispatch())
    record = result.usage[0]
    assert record.model == "claude-sonnet-5"
    assert (record.input, record.cache_write, record.cache_read, record.output) == (10, 20, 30, 40)


def test_non_zero_exit_is_an_error_not_an_empty_success(tmp_home, stub_claude, monkeypatch):
    monkeypatch.setenv("STUB_CLAUDE_FAIL_EXIT", "2")
    result = inference.infer(_bootstrap_dispatch())
    assert not result.ok
    assert "exit 2" in result.error


def test_sigterm_exit_143_is_reported_distinctly(tmp_home, stub_claude, monkeypatch):
    monkeypatch.setenv("STUB_CLAUDE_FAIL_EXIT", "143")
    result = inference.infer(_bootstrap_dispatch())
    assert not result.ok
    assert "interrupted" in result.error.lower()


def test_unparseable_json_is_an_error(tmp_home, stub_claude, monkeypatch):
    monkeypatch.setenv("STUB_CLAUDE_BAD_JSON", "1")
    result = inference.infer(_bootstrap_dispatch())
    assert not result.ok
    assert "json" in result.error.lower()


def test_missing_binary_is_an_error(tmp_home, monkeypatch):
    monkeypatch.setenv("PATH", "")
    result = inference.infer(_bootstrap_dispatch())
    assert not result.ok
    assert "not on PATH" in result.error


def test_infer_never_retries(tmp_home, stub_claude, monkeypatch):
    # Retry policy belongs to the caller (spec 3.6, spec 14).
    monkeypatch.setenv("STUB_CLAUDE_FAIL_EXIT", "1")
    inference.infer(_bootstrap_dispatch())
    assert len(stub_claude.calls()) == 1


def test_concurrency_cap_holds_across_processes(tmp_home, stub_claude, tmp_path, monkeypatch):
    """A per-process counter would bound nothing (spec 3.6)."""
    import subprocess
    import sys
    import textwrap
    import time

    pool = paths.dispatch_slots() / "thinker"      # two pools, per spec 5.1
    pool.mkdir(parents=True, exist_ok=True)
    ready = tmp_path / "slot-ready"

    # Occupy the single thinker slot from another process.
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import pathlib, time
        from taller import locking
        with locking.file_lock({str(pool / 'slot-0.lock')!r}):
            pathlib.Path({str(ready)!r}).write_text("1")
            time.sleep(6)
    """)])
    try:
        # Wait for the holder to really have it, rather than guessing.
        deadline = time.monotonic() + 20
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "holder never acquired the slot"

        # Time the ACQUISITION, not the whole dispatch: timing infer() would pass
        # with a per-process semaphore whenever a dispatch itself took >= 1.5s.
        started = time.monotonic()
        acquired = inference._acquire_slot(pool, limit=1)
        waited = time.monotonic() - started
        acquired.__exit__(None, None, None)
        assert waited >= 1.5, f"slot acquisition did not block (waited {waited:.1f}s)"
    finally:
        holder.kill()
        holder.wait()


# --- the accent that would have corrupted a Spanish constitution --------------

def test_non_ascii_survives_the_round_trip(tmp_home, stub_claude, monkeypatch):
    """Without an explicit encoding, subprocess uses the locale encoding - cp1252
    on Windows - and a UTF-8 answer decodes to mojibake that still parses as JSON.
    Verified: 'reunion' with an accent came back with U+00F3 replaced by
    U+00C3 U+00B3, silently. No other fixture contains an accented character."""
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", json.dumps({
        "session_id": "s",
        "is_error": False,
        "result": "la reunión terminó — café ñ",
        "usage": {"input_tokens": 1, "cache_creation_input_tokens": 0,
                  "cache_read_input_tokens": 0, "output_tokens": 1},
    }, ensure_ascii=False))
    result = inference.infer(_bootstrap_dispatch())
    assert result.ok
    assert result.value == "la reunión terminó — café ñ"
    assert "Ã" not in result.value, "the answer was decoded with the wrong codec"


def test_a_prompt_with_non_ascii_does_not_crash(tmp_home, stub_claude):
    """U+2192 is outside cp1252 and appears throughout this project's own
    documents. Encoding the prompt with the locale codec raised UnicodeEncodeError
    out of infer(), which is neither of its two documented failure classes."""
    result = inference.infer(_bootstrap_dispatch(
        prompt="rename módulo → módulos, and keep the ñ"
    ))
    assert result.ok


def test_a_slot_is_released_after_the_body_raises(tmp_home, stub_claude, monkeypatch):
    """Locks in the release guarantee, not just the exception's survival."""
    def boom(*args, **kwargs):
        raise OSError("BODY BOOM")

    # The dispatch body: where the CLI is spawned and waited on.
    monkeypatch.setattr(inference, "_run_bounded", boom)
    pool = paths.dispatch_slots() / "worker"
    with pytest.raises(OSError):
        inference.infer(_bootstrap_dispatch())
    assert not list(pool.glob("*.lock")), "a slot leaked when the body raised"


def test_omitting_tools_does_not_fail_open(tmp_home, stub_claude):
    """An empty allowlist meant no --allowedTools at all, so the dispatch ran with
    the CLI's full default tool set under --permission-mode dontAsk."""
    d = _bootstrap_dispatch(role="gate_ux", tools=[], forbidden=[])
    inference.infer(d)
    flags = stub_claude.flags()
    assert "--allowedTools" in flags
    for write_tool in ("Write", "Edit", "NotebookEdit"):
        assert write_tool not in flags, f"a read-only gate was granted {write_tool}"


def test_a_cwd_that_does_not_exist_is_refused(tmp_home, stub_claude, tmp_path):
    """Creating an arbitrary cwd turned a stale worktree path into an empty
    directory, and the dispatch then ran against nothing and reported success."""
    with pytest.raises(inference.InferenceError, match="not a directory"):
        inference.infer(_bootstrap_dispatch(cwd=tmp_path / "does-not-exist"))


def test_a_role_is_briefed_with_only_its_own_slices(tmp_home):
    """Spec 3.6.0. An earlier version concatenated every slice, so a UX gate was
    briefed with the security and product slices too.

    Asserted against `_brief` directly rather than against argv, because the
    briefing is a single multi-line argument and the Windows `.cmd` stub shim
    cannot carry a newline: cmd.exe re-parses `%*`, and a newline terminates a
    command line. The real binary is spawned without a shell and receives it
    intact, so this is a limit of the harness, not of the product. The separate
    test below covers the argv plumbing.
    """
    ruleset = {
        "slices": {
            "ux": {"text": "UX-SLICE"},
            "brand": {"text": "BRAND-SLICE"},
            "conventions": {"text": "CONV-SLICE"},
            "security": {"text": "SECURITY-SLICE"},
            "product": {"text": "PRODUCT-SLICE"},
        },
    }
    dispatch = _bootstrap_dispatch(role="gate_ux", ruleset=ruleset)
    brief = inference._brief(dispatch)

    assert "UX-SLICE" in brief
    assert "BRAND-SLICE" in brief
    assert "CONV-SLICE" in brief
    assert "SECURITY-SLICE" not in brief, "gate_ux was briefed with the security slice"
    assert "PRODUCT-SLICE" not in brief, "gate_ux was briefed with the product slice"


def test_a_missing_slice_is_skipped_not_an_error(tmp_home):
    """A project need not provide every slice."""
    dispatch = _bootstrap_dispatch(role="gate_ux", ruleset={"slices": {"ux": {"text": "ONLY-UX"}}})
    assert inference._brief(dispatch) == "ONLY-UX"


def test_the_briefing_reaches_append_system_prompt(tmp_home, stub_claude):
    """The argv plumbing, with a single-line briefing the shim can carry."""
    inference.infer(_bootstrap_dispatch(role="gate_ux", system="ONE-LINE-BRIEF"))
    flags = stub_claude.flags()
    assert "--append-system-prompt" in flags
    assert "ONE-LINE-BRIEF" in flags


def test_a_ruleset_dispatch_resolves_its_model(tmp_home, stub_claude):
    """RuleSet["models"] holds aliases, exactly like HubConfig, so one resolver
    serves both. An earlier spec comment said otherwise and this raised."""
    ruleset = {
        "slices": {},
        "models": config.SHIPPED_DEFAULTS["models"],
        "model_aliases": config.SHIPPED_DEFAULTS["model_aliases"],
        "effort": config.SHIPPED_DEFAULTS["effort"],
        "concurrency": config.SHIPPED_DEFAULTS["concurrency"],
        "paths": {"tests_dir": "tests"},
    }
    result = inference.infer(_bootstrap_dispatch(role="gate_security", ruleset=ruleset))
    assert result.ok
    assert "--model opus" in stub_claude.flags()
