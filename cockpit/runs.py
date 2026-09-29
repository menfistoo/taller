"""The run a click starts, and how the page watches it (spec 12).

The cockpit never hosts the chief (spec 3.1). Approving here starts the very
same program a terminal would - `taller ticket run` - in its own process, and
the page only reads the file that process writes. A web server that carried a
ticket inside a request would hold a worker for the length of a whole dispatch,
lose the work if the browser tab closed, and put the chief behind a socket that
spec 3.1 says it must never be behind.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from taller import locking, paths

# The tail of the run's output the page shows. A dispatch can print hundreds of
# lines; what she needs is where it has got to, not the whole transcript.
LINES_SHOWN = 40

# Live children of THIS server, by run id. Only these can report an exit code:
# a run started before a restart is watched by its recorded process id instead.
_children: dict[str, subprocess.Popen] = {}


def runs_dir() -> Path:
    """Where a run's output and its process id are kept.

    A function, not a constant: `paths.run_dir()` reads the home directory when
    it is called, and a constant computed at import would pin the first one seen.
    """
    return paths.run_dir() / "cockpit-runs"


def run_id(name: str, ticket_id: int) -> str:
    """One run per ticket. Starting it again replaces what the last one left."""
    return f"{name}-{ticket_id:04d}"


def log_path(rid: str) -> Path:
    return runs_dir() / f"{rid}.log"


def start(project: Path, name: str, ticket_id: int) -> str:
    """Start `taller ticket run <id>` for this ticket and return its run id.

    Returns as soon as the process exists; nothing here waits for it.
    """
    rid = run_id(name, ticket_id)
    runs_dir().mkdir(parents=True, exist_ok=True)
    child = _spawn(argv(project, ticket_id), log_path(rid))
    _children[rid] = child
    remember(rid, child.pid)
    return rid


def argv(project: Path, ticket_id: int) -> list[str]:
    """The command line. `-m taller.cli` rather than the `taller` script, because
    the script may not be on PATH of the process that is serving these pages."""
    return [sys.executable, "-m", "taller.cli", "ticket", "run", str(ticket_id),
            "--path", str(project)]


def progress(rid: str) -> dict[str, Any]:
    """Where the run has got to: `{"running": bool, "lines": [...], "code": int|None}`.

    Reads a file and a process's state. It never blocks, so a request that asks
    for it returns at once whatever the run is doing.
    """
    pid = _recorded_pid(rid)
    child = _children.get(rid)
    if child is not None and child.pid == pid:
        code = child.poll()
        running = code is None
    else:
        # A run this server did not start - one from before a restart - has no
        # exit code to report: only a parent is told how its child ended. Its
        # process id says whether something is alive; what that something IS has
        # to be asked, because the machine gives the number out again, and a
        # reused one had the page claiming for ever that Taller was working.
        running = pid is not None and _alive(pid) and _looks_like_a_run(pid)
        code = None
    return {"running": running, "lines": _tail(log_path(rid)), "code": code}


def remember(rid: str, pid: int) -> None:
    """Keep the run's process id, so a restarted server still knows what is going."""
    runs_dir().mkdir(parents=True, exist_ok=True)
    locking.atomic_write(runs_dir() / f"{rid}.json",
                         json.dumps({"pid": int(pid)}).encode("utf-8"))


def _recorded_pid(rid: str) -> int | None:
    try:
        kept = json.loads((runs_dir() / f"{rid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pid = kept.get("pid")
    return int(pid) if isinstance(pid, int) else None


def _alive(pid: int) -> bool:
    return locking._pid_alive(pid)


def _looks_like_a_run(pid: int) -> bool:
    """Is the process wearing this number still a Python running Taller?

    Asked of the machine, not assumed. When the machine cannot say, the answer is
    yes: a run that is going and is reported as finished is the worse mistake -
    she would start a second one on the same ticket.
    """
    name = _process_name(pid)
    if not name:
        return True
    return Path(sys.executable).name.lower() in name.lower() or "python" in name.lower()


def _process_name(pid: int) -> str:
    """The program the process is running, or "" when it cannot be asked."""
    if sys.platform == "win32":
        asked = ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"]
    else:
        asked = ["ps", "-p", str(pid), "-o", "comm="]
    try:
        out = subprocess.run(asked, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    first = (out.stdout.strip().splitlines() or [""])[0].strip()
    if sys.platform == "win32":
        # A row is CSV, `"image.exe","1234",...`; anything else is tasklist's own
        # "No tasks are running which match" notice, which names no program.
        return first.split('","')[0].strip('"') if first.startswith('"') else ""
    return first


def _tail(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-LINES_SHOWN:]


def _spawn(command: list[str], log: Path) -> subprocess.Popen:
    """Start the command with its output going to `log`, and do not wait for it."""
    extra: dict[str, Any] = {}
    if sys.platform == "win32":
        # Its own process group, so a Ctrl-C in the terminal that started the
        # cockpit does not also stop a ticket that is halfway through a dispatch.
        extra["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        extra["start_new_session"] = True
    with open(log, "wb") as handle:
        return subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=dict(os.environ), **extra)
