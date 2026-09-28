"""`taller hook session-start`: the briefing a Claude Code chat starts with.

Spec 3.1: the chief is never told what the project is - in a session the same
briefing arrives through a SessionStart hook. The plugin's `hooks/hooks.json`
runs this command; Claude Code sends the event as JSON on stdin (`cwd` among
it) and adds whatever this prints to the chat's context.

A hook must never break a session, so anything wrong - not a Taller project,
bad input, a broken registry - prints nothing and exits 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .. import registry, tickets
from ..prompter import Prompter

BRIEFING_MAX = 4000          # §3.1's ~500-token briefing, plus the open tickets
INDEX = ".taller/constitution/00-index.md"


def read_event() -> Any:
    """Claude Code sends UTF-8; Windows' stdin would decode it in the ANSI code page,
    and an accented folder would then match no project (plugin review, I6)."""
    stream = getattr(sys.stdin, "buffer", None)
    raw = stream.read().decode("utf-8") if stream is not None else sys.stdin.read()
    return json.loads(raw or "{}")


def session_start(args: Any, prompter: Prompter) -> int:
    try:
        event = read_event()
        text = briefing(Path(event["cwd"])) if isinstance(event, dict) and \
            event.get("cwd") else ""
    except Exception:                    # a hook never breaks the session it serves
        return 0
    if text:
        print(text, flush=True)
    return 0


def briefing(cwd: Path) -> str:
    """What a chat standing in `cwd` should know; "" when it is not a Taller project."""
    entry = _project_containing(cwd)
    if entry is None:
        return ""
    project = Path(entry["path"])
    lines = [f"This is {entry['name']}, a project Taller runs (profile "
             f"{entry['profile']}). Its rules, as Taller routes them:", ""]
    index = tickets.read_main(project, INDEX)
    if index:
        lines.append(index.decode("utf-8", errors="replace").strip())
    listed, _ = tickets.list_tickets(project)
    open_ = [t for t in listed if t.get("stage") != "close"]
    lines += ["", "Open tickets:" if open_ else "No open tickets."]
    for ticket in open_:
        blocked = ticket.get("blocked")
        lines.append(f"- {ticket['id']:04d} · {tickets._label(ticket['stage'])} · "
                     f"{ticket['title']}"
                     + (f" · blocked: {blocked.get('reason', '')}" if blocked else ""))
    tail = ["", "Use /taller:status to see a ticket, /taller:new to start one."]
    text = "\n".join(lines)
    room = BRIEFING_MAX - len("\n".join(tail)) - len("\n[... more tickets ...]")
    if len(text) > room:
        text = text[:room].rsplit("\n", 1)[0] + "\n[... more tickets ...]"
    return text + "\n".join(tail)


def _project_containing(cwd: Path) -> dict[str, Any] | None:
    here = cwd.resolve()
    for entry in registry.list_projects():
        root = Path(entry["path"])
        if (here == root or root in here.parents) and registry.is_adopted(entry):
            return entry
    return None
