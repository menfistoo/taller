"""Answers Taller keeps for a command run from a Claude Code chat.

A chat cannot type into a prompt. When a command needs an answer it stops with
`NEEDS <id>`; the chat asks the owner and records the answer with
`taller answer <id> <value...>`, then runs the same command again. Taller keeps
those answers itself (plugin review, C1/C3/I3), so:

- a sheet belongs to one command - the directory it ran in and its arguments -
  and is deleted when that command finishes, so one command's answers never
  answer another's;
- a question asked twice in one run (an edit loop, a keep/remove toggle) has
  its answers kept in order and replayed on every run;
- the chat writes no file and needs no permission beyond running `taller`.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from . import locking, paths
from .errors import ConfigError

STALE_S = 24 * 3600         # a sheet no command came back for within a day is dropped

Sheet = dict[str, list[Any]]        # question id -> answers, in the order asked


def folder() -> Path:
    return paths.run_dir() / "answers"


def key(cwd: Path | str, argv: list[str]) -> str:
    raw = json.dumps([str(Path(cwd).resolve()), list(argv)])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def load(sheet_key: str) -> Sheet:
    _drop_stale()
    path = folder() / f"{sheet_key}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    answers = data.get("answers") if isinstance(data, dict) else None
    return {str(k): list(v) for k, v in (answers or {}).items() if isinstance(v, list)}


def needs(sheet_key: str, cwd: Path | str, argv: list[str], answers: Sheet) -> None:
    """The command stopped on a question: keep its sheet and point `answer` at it."""
    folder().mkdir(parents=True, exist_ok=True)
    locking.atomic_write_text(folder() / f"{sheet_key}.json", json.dumps(
        {"cwd": str(cwd), "argv": list(argv), "answers": answers}, ensure_ascii=False))
    locking.atomic_write_text(folder() / "pending", sheet_key)


def finished(sheet_key: str) -> None:
    """The command ran to its end: its answers are spent."""
    (folder() / f"{sheet_key}.json").unlink(missing_ok=True)
    pending_file = folder() / "pending"
    try:
        if pending_file.read_text(encoding="utf-8").strip() == sheet_key:
            pending_file.unlink(missing_ok=True)
    except OSError:
        pass


def pending() -> str | None:
    try:
        sheet_key = (folder() / "pending").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return sheet_key if (folder() / f"{sheet_key}.json").is_file() else None


def add(qid: str, value: Any) -> dict[str, Any]:
    """Record one answer for the command waiting on it; returns that command's record."""
    sheet_key = pending()
    if sheet_key is None:
        raise ConfigError("Nothing is waiting for an answer. Run the command first; "
                          "when it prints NEEDS <id>, answer that.")
    path = folder() / f"{sheet_key}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record.setdefault("answers", {}).setdefault(qid, []).append(value)
    locking.atomic_write_text(path, json.dumps(record, ensure_ascii=False))
    return record


def _drop_stale() -> None:
    now = time.time()
    for path in folder().glob("*.json") if folder().is_dir() else []:
        try:
            if now - path.stat().st_mtime > STALE_S:
                path.unlink()
        except OSError:
            pass
