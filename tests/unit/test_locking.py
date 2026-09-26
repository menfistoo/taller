import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from taller import locking
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
            from taller import locking
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
        with pytest.raises(LockTimeout):
            with locking.file_lock(lock, timeout=5):
                target.write_text("clobbered", encoding="utf-8")
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
