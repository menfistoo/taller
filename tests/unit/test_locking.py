import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from taller import locking, paths
from taller.errors import LockTimeout


def test_lock_is_reentrant_within_a_process(tmp_path: Path):
    lock = tmp_path / "a.lock"
    with locking.file_lock(lock):
        with locking.file_lock(lock):  # must NOT deadlock — spec 10.3
            pass


def test_lock_releases_only_at_the_outermost_exit(tmp_path: Path):
    lock = tmp_path / "a.lock"
    with locking.file_lock(lock):
        with locking.file_lock(lock):
            pass
        assert locking.held(lock)  # inner exit must not release
    assert not locking.held(lock)


def test_second_process_times_out_and_the_file_survives(tmp_path: Path):
    lock = tmp_path / "a.lock"
    target = tmp_path / "data.txt"
    target.write_text("original", encoding="utf-8")

    ready = tmp_path / "ready"
    holder = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
            import pathlib, time
            from taller import locking, paths
            with locking.file_lock({str(lock)!r}):
                pathlib.Path({str(ready)!r}).write_text("1")
                time.sleep(8)
        """)],
    )
    try:
        import time
        deadline = time.monotonic() + 20          # a readiness file, not a guessed sleep
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "holder process never acquired the lock"
        started = time.monotonic()
        with pytest.raises(LockTimeout):
            with locking.file_lock(lock, timeout=5):
                target.write_text("clobbered", encoding="utf-8")
        elapsed = time.monotonic() - started
        # The name says "times out"; assert it actually did. Without this,
        # timeout=5 regressing to timeout=0 would still pass.
        assert 4.0 <= elapsed < 9.0, f"timeout took {elapsed:.1f}s, expected ~5s"
        assert target.read_text(encoding="utf-8") == "original"
    finally:
        holder.kill()
        holder.wait()


def test_a_non_reentrant_lock_refuses_the_same_thread(tmp_path: Path):
    """Semaphore slots must not be re-entrant, or a nested dispatch would exceed
    the concurrency cap silently."""
    lock = tmp_path / "slot-0.lock"
    with locking.file_lock(lock, reentrant=False):
        with pytest.raises(LockTimeout, match="semaphore slot"):
            with locking.file_lock(lock, timeout=0.1, reentrant=False):
                pass


def test_atomic_write_replaces_in_place(tmp_path: Path):
    target = tmp_path / "out.txt"
    locking.atomic_write(target, b"hello")
    assert target.read_bytes() == b"hello"
    locking.atomic_write(target, b"goodbye")
    assert target.read_bytes() == b"goodbye"
    # No temporary files left behind.
    assert [p.name for p in tmp_path.iterdir()] == ["out.txt"]


def test_atomic_write_creates_parent_directories(tmp_path: Path):
    target = tmp_path / "deep" / "nested" / "out.txt"
    locking.atomic_write(target, b"x")
    assert target.read_bytes() == b"x"


# --- the behaviours the first draft left untested -----------------------------

def test_the_lock_file_itself_survives_a_nested_exit(tmp_path: Path):
    """Checking only the depth counter would pass an implementation that unlinked
    the file at the inner exit — i.e. cross-process exclusion silently broken,
    which is the exact failure this test exists to catch."""
    lock = tmp_path / "a.lock"
    with locking.file_lock(lock):
        assert lock.exists()
        with locking.file_lock(lock):
            assert lock.exists()
        assert lock.exists(), "inner exit removed the lock file"
    assert not lock.exists()


def test_re_entrancy_is_per_thread_not_per_process(tmp_path: Path):
    """The module's central design decision, argued in its docstring against the
    spec's literal wording. Nothing verified it."""
    import threading

    lock = tmp_path / "a.lock"
    outcome: dict[str, object] = {}

    def other_thread():
        try:
            with locking.file_lock(lock, timeout=0.3):
                outcome["result"] = "acquired"
        except LockTimeout:
            outcome["result"] = "timed out"

    with locking.file_lock(lock):
        assert locking.held(lock)
        t = threading.Thread(target=other_thread)
        t.start()
        t.join(timeout=10)

    # Thread B must NOT believe it holds thread A's lock.
    assert outcome["result"] == "timed out"


def test_the_three_named_locks_are_usable_context_managers(tmp_home: Path):
    """hub_lock/registry_lock/project_lock are the actual spec 10.3 deliverable
    and no test entered any of them. They pass `timeout` positionally, so a
    future reordering of file_lock's signature would break all three silently."""
    with locking.hub_lock():
        assert locking.held(paths.hub_lock())
    with locking.registry_lock():
        assert locking.held(paths.registry_lock())
    with locking.project_lock("demo"):
        assert locking.held(paths.project_lock("demo"))
    assert not locking.held(paths.hub_lock())


def test_a_lock_left_by_a_dead_process_is_reaped(tmp_path: Path):
    """Without this, a holder killed by TerminateProcess or a power loss blocks
    every future invocation, and the PID written into the lock file is decoration
    rather than a safety feature."""
    lock = tmp_path / "stale.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("999999999", encoding="ascii")   # a PID that cannot be alive

    started = time.monotonic()
    with locking.file_lock(lock, timeout=5):
        pass
    elapsed = time.monotonic() - started
    assert elapsed < 2, f"reaping a dead holder's lock waited {elapsed:.1f}s"
    assert not lock.exists()


def test_a_lock_held_by_a_live_process_is_not_reaped(tmp_path: Path):
    """The reaper must not mistake a working process for a dead one."""
    lock = tmp_path / "live.lock"
    lock.write_text(str(os.getpid()), encoding="ascii")   # our own PID: alive
    with pytest.raises(LockTimeout):
        with locking.file_lock(lock, timeout=0.5):
            pass
    assert lock.exists(), "the reaper removed a live holder's lock"


def test_atomic_write_is_safe_from_two_threads(tmp_path: Path):
    """A PID-only temp name made two threads race on one path: on Windows both
    raised PermissionError and the target ended up ABSENT, not merely blended."""
    import threading

    target = tmp_path / "shared.txt"
    errors: list[BaseException] = []

    def writer(payload: bytes):
        try:
            for _ in range(20):
                locking.atomic_write(target, payload)
        except BaseException as exc:      # noqa: BLE001 - recording, not handling
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(p,))
               for p in (b"a" * 64, b"b" * 64)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"concurrent atomic_write raised: {errors!r}"
    assert target.exists(), "the target vanished"
    assert target.read_bytes() in (b"a" * 64, b"b" * 64), "a partial write landed"
    assert not list(tmp_path.glob(".shared.txt.tmp*")), "a temp file leaked"
