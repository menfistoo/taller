"""The Diff every Python gate reads (spec 10.2) - built once, from git.

`Diff` carries what three constitution rules need and a bare patch cannot give:
each commit's message (commit shape), each file's status (root markdown and
single-use scripts are defined on NEW files only), the added lines with their
numbers (literals), and the file's full text (whole-file rules). Ticket files
under `.taller/work/` are excluded: they are Taller's, not the change.

A file that is binary or not UTF-8 stays in the list with `content: None` and no
lines, so a gate can say it skipped it rather than crash on it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

Diff = dict[str, Any]
IGNORED = ".taller/work/"
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _git(repo: Path | str, *args: str) -> bytes:
    completed = subprocess.run(["git", "-C", str(repo), "-c", "core.quotepath=false", *args],
                               capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace").strip())
    return completed.stdout


def _text(raw: bytes | None) -> str | None:
    if raw is None or b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def build(repo: Path | str, base: str, head: str) -> Diff:
    """The change on `head` since it left `base` (three-dot), ticket files excluded."""
    spec = f"{base}...{head}"
    commits = []
    for line in _git(repo, "log", "--format=%H%x1f%s", f"{base}..{head}").decode(
            "utf-8", errors="replace").splitlines():
        sha, _, message = line.partition("\x1f")
        commits.append({"sha": sha, "message": message})

    files = []
    for line in _git(repo, "diff", "--name-status", "--no-renames", spec).decode(
            "utf-8", errors="replace").splitlines():
        status, _, path = line.partition("\t")
        if not path or path.startswith(IGNORED):
            continue
        status = status[:1]
        content = None if status == "D" else _text(_show(repo, head, path))
        added, removed = ([], []) if content is None and status != "D" else _lines(
            repo, spec, path)
        files.append({"path": path, "status": status, "added": added, "removed": removed,
                      "content": content})
    return {"base": base, "head": head, "commits": list(reversed(commits)), "files": files,
            "tracked": _tracked(_git(repo, "ls-tree", "-r", "--name-only", head))}


def _tracked(listing: bytes) -> list[str]:
    """Every path at the head, ticket files excluded: which imports are local."""
    paths = listing.decode("utf-8", errors="replace").splitlines()
    return sorted(path for path in paths if path and not path.startswith(IGNORED))


def _show(repo: Path | str, ref: str, path: str) -> bytes | None:
    completed = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{path}"],
                               capture_output=True)
    return completed.stdout if completed.returncode == 0 else None


def _lines(repo: Path | str, spec: str, path: str) -> tuple[list[dict], list[dict]]:
    """Added and removed lines with their numbers, from a zero-context patch."""
    patch = _text(_git(repo, "diff", "-U0", "--no-renames", spec, "--", path))
    added: list[dict] = []
    removed: list[dict] = []
    if patch is None:
        return added, removed
    old_line = new_line = 0
    for line in patch.splitlines():
        hunk = _HUNK.match(line)
        if hunk:
            old_line, new_line = int(hunk.group(1)), int(hunk.group(3))
            continue
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            added.append({"line": new_line, "text": line[1:]})
            new_line += 1
        elif line.startswith("-"):
            removed.append({"line": old_line, "text": line[1:]})
            old_line += 1
    return added, removed


def tree(repo: Path | str) -> Diff:
    """Every tracked file in the working tree, all lines as added - for `scan()`."""
    repo = Path(repo)
    files = []
    tracked = _tracked(_git(repo, "ls-files"))
    for path in tracked:
        try:
            content = _text((repo / path).read_bytes())
        except OSError:
            continue
        lines = content.splitlines() if content is not None else []
        files.append({"path": path, "status": "A", "content": content, "removed": [],
                      "added": [{"line": n, "text": text} for n, text in enumerate(lines, 1)]})
    return {"base": "", "head": "HEAD", "commits": [], "files": files, "tracked": tracked}
