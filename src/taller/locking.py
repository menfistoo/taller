"""File locks and atomic writes.

Locks are re-entrant within a process, because spec 7.6 holds the project lock
for a whole chief dispatch while a stage transition inside that window takes the
same lock through gitio.commit_to_main(). A non-re-entrant lock would deadlock
against itself on the most common path in the system.

Cross-process exclusion uses an exclusive create (O_EXCL), which is atomic on
both POSIX and Windows and needs no third-party dependency.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Iterator

from . import paths
from .errors import LockTimeout

DEFAULT_TIMEOUT = 5.0
_POLL = 0.05

# lock path (resolved, as str) -> re-entrancy depth, per THREAD.
# Thread-local because the cockpit (spec 12) is a threaded server in one process,
# where a process-wide counter would let thread B believe it holds thread A's lock.
_state = threading.local()


def _depths() -> dict[str, int]:
    if not hasattr(_state, "depth"):
        _state.depth = {}
    return _state.depth


def held(lock_path: Path | str) -> bool:
    """True when this thread currently holds the lock. Reads without mutating."""
    return _depths().get(str(Path(lock_path).resolve()), 0) > 0


@contextlib.contextmanager
def file_lock(
    lock_path: Path | str,
    timeout: float = DEFAULT_TIMEOUT,
    reentrant: bool = True,
) -> Iterator[None]:
    """Hold an exclusive lock. Re-entrant within this thread by default.

    Raises LockTimeout rather than waiting indefinitely or forcing, so a stuck
    holder produces a clear message instead of a hang.

    `reentrant=False` is for counting semaphores. A re-entrant lock used as a
    semaphore silently stops capping: the second acquisition in the same thread
    succeeds by design, so a nested dispatch would exceed the concurrency limit
    without any error. Verified both ways before this was written.
    """
    path = Path(lock_path).resolve()
    key = str(path)
    depth = _depths()

    if depth.get(key, 0) > 0:      # already ours
        if not reentrant:
            raise LockTimeout(
                f"{path} is already held by this thread and was requested "
                f"non-re-entrantly. It is a semaphore slot, not a mutex."
            )
        depth[key] += 1             # just count deeper
        try:
            yield
        finally:
            depth[key] -= 1
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except (FileExistsError, PermissionError):
            # PermissionError matters on Windows: a file in the delete-pending
            # state — precisely the window the previous holder's unlink() opens —
            # reports ERROR_ACCESS_DENIED, not "already exists". Catching only
            # FileExistsError would escape this loop as a bare OSError under the
            # cross-process contention this module exists to handle.
            if _reap_if_stale(path):
                continue
            if time.monotonic() >= deadline:
                raise LockTimeout(_busy(path, timeout))
            time.sleep(_POLL)

    # From here the lock file exists, so every path must be able to remove it.
    # An unguarded os.write between the open and the try left a file that could
    # not be deleted at all on Windows, because the leaked handle kept it open.
    try:
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
        finally:
            os.close(fd)
        depth[key] = 1
        yield
    finally:
        depth.pop(key, None)
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def _busy(path: Path, timeout: float) -> str:
    """Why the lock could not be taken. A live holder is named and never offered
    for removal: deleting a working process's lock lets two writers collide."""
    try:
        raw = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        raw = ""
    if raw.isdigit() and _pid_alive(int(raw)):
        return (f"Taller is busy: process {raw} is still working on this (a ticket run, "
                f"perhaps). Wait for it to finish, then try again.")
    return (f"Could not take the lock at {path} within {timeout:g}s. Another Taller "
            f"process is probably still working; `taller doctor` tells whether it is.")


def _reap_if_stale(path: Path) -> bool:
    """Remove a lock whose owning process is gone. True when one was reaped.

    The PID is written into the lock file precisely so it can be read back here.
    Without this, a holder killed by TerminateProcess, an OOM or a power loss
    leaves a lock that blocks every future invocation and can only be cleared by
    hand — and the PID write would be decoration rather than a safety feature.
    """
    try:
        raw = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return False                    # unreadable: assume a live holder
    if not raw.isdigit():
        return False
    if _pid_alive(int(raw)):
        return False
    with contextlib.suppress(OSError):
        path.unlink()
        return True
    return False


def is_stale(path: Path | str) -> bool:
    """A lock file whose recorded owner is dead. Reads only; `doctor` reports it.

    An unreadable or PID-less file is not called stale: a holder may be mid-write.
    """
    try:
        raw = Path(path).read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return False
    return raw.isdigit() and not _pid_alive(int(raw))


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # No signal 0 on Windows; ask the process list instead.
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace",
        )
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                     # exists, owned by someone else
    return True


# --- the three named locks of spec 10.2, as context managers ----------------

def hub_lock(timeout: float = DEFAULT_TIMEOUT):
    """Hub amendments."""
    return file_lock(paths.hub_lock(), timeout)


def registry_lock(timeout: float = DEFAULT_TIMEOUT):
    """projects.json writes."""
    return file_lock(paths.registry_lock(), timeout)


def project_lock(project_name: str, timeout: float = DEFAULT_TIMEOUT):
    """A project's main-side files, and a whole chief dispatch (spec 7.6)."""
    return file_lock(paths.project_lock(project_name), timeout)


def atomic_write(target: Path | str, data: bytes) -> None:
    """Write via a temporary file in the same directory, then os.replace.

    Same directory so the replace cannot cross a filesystem boundary, which is
    what makes it atomic.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    # PID + thread + a random token. PID alone was not enough: this module's own
    # docstring justifies thread-locality by pointing at a threaded server, and two
    # threads computing the same temp name do not blend their writes - they race,
    # both raise PermissionError on Windows, and the target ends up ABSENT.
    tmp = target.with_name(
        f".{target.name}.tmp{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex[:8]}"
    )
    try:
        tmp.write_bytes(data)
        _replace_with_retry(tmp, target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def _replace_with_retry(tmp: Path, target: Path, attempts: int = 50) -> None:
    """os.replace, retried briefly on a transient Windows denial.

    On Windows, replacing a target another thread or process is momentarily
    holding raises PermissionError (ERROR_ACCESS_DENIED) even when the temp name
    is unique. Discovered by testing two threads writing one target: the write
    failed outright rather than one of them simply winning. The replace is atomic
    once it succeeds; retrying only widens the window in which it can.
    """
    for attempt in range(attempts):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(_POLL)


def atomic_write_text(target: Path | str, text: str) -> None:
    """Always UTF-8 with LF endings, so generated files are byte-stable across
    platforms — spec 4.6's tamper check compares bytes."""
    atomic_write(target, text.replace("\r\n", "\n").encode("utf-8"))
