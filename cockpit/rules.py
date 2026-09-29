"""The Constitution screen: the rules a project is held to, and amending them.

Chain 2 (spec 4.4) concatenates several files into one slice, so what a gate
reads is a *joined* text - but an edit has to go back to the file it came from.
This module therefore shows each source file on its own, and saving one is
exactly what `taller amend` does: write, commit, and refresh every project the
change reaches (4.6). A rule that changed without the snapshots moving would be
a rule nothing enforces.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from taller import constitution, generated, gitio, hub, locking, paths, registry
from taller.errors import ConfigError

from . import reading


def slices(project_name: str) -> dict[str, Any]:
    """Every slice that reaches this project, file by file."""
    entry = reading.entry_for(project_name)
    path = Path(entry["path"])
    ruleset = constitution.resolve(path)
    listed = []
    for name in constitution.SLICE_NAMES:
        resolved = (ruleset["slices"] or {}).get(name)
        if not resolved:
            continue
        listed.append({
            "name": name,
            "sources": [_source(Path(source)) for source in resolved["sources"]],
        })
    return {
        "project": entry["name"],
        "projects": [row["name"] for row in reading.project_entries()
                     if row["available"]],
        "profile": entry.get("profile", ""),
        "slices": listed,
        "overrides": list(ruleset.get("overrides") or []),
        "hub_sha": ruleset.get("hub_sha", ""),
        "branch": gitio.git(path, "rev-parse", "--abbrev-ref", "HEAD",
                            check=False).stdout.strip(),
    }


def _source(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "where": "hub" if _inside(path, paths.hub()) else "project",
        "text": path.read_text(encoding="utf-8") if path.is_file() else "",
    }


def save(project_name: str, path: str, text: str, reason: str) -> list[str]:
    """Amend one rule file. Returns the lines to show her.

    The path is checked against the files this project actually resolves, so a
    form field can only ever reach a rule - never any other file on the machine.
    """
    entry = reading.entry_for(project_name)
    project = Path(entry["path"])
    target = _one_of_the_rules(project, path)
    reason = str(reason).strip()
    if not reason:
        raise ConfigError("An amendment needs a reason; it is kept with the rule, and it "
                          "is what tells the next reader why the rule says what it says.")

    if _inside(target, paths.hub()):
        relative = target.relative_to(paths.hub()).as_posix()
        with locking.hub_lock():
            locking.atomic_write_text(target, text)
        hub.commit(f"amend: {reason}")
        touched = generated.refresh_for_hub_paths([relative])
        lines = [f"Amended the hub rule {relative}."]
        lines += [f"  refreshed {name} (sync: {sync})" for name, sync in touched]
        return lines + ([] if touched else ["  No adopted project uses it yet."])

    branch = gitio.git(project, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != gitio.MAIN_BRANCH:
        # `taller amend` refuses the same way: a rule amended on a ticket branch
        # would vanish with the branch, and would not be a rule in the meantime.
        raise ConfigError(f"{entry['name']} is on {branch}. A rule is amended on "
                          f"{gitio.MAIN_BRANCH}: switch to it, then try again.")
    relative = target.relative_to(project).as_posix()
    with locking.project_lock(registry.get_project(project)["name"]):
        locking.atomic_write_text(target, text)
    gitio.git(project, "add", "--", relative)
    gitio.git(project, "commit", "--quiet", "-m", f"amend: {reason}", "--", relative)
    sync = generated.refresh(project)
    return [f"Amended {entry['name']}'s rule {relative}; refreshed it (sync: {sync})."]


def _one_of_the_rules(project: Path, path: str) -> Path:
    """The file, only if this project really resolves it. Otherwise a refusal.

    Compared resolved, so `..` in a form field cannot climb anywhere: this is the
    one check standing between a text box and every file on the machine.
    """
    wanted = Path(path).resolve()
    allowed = {Path(source).resolve()
               for resolved in (constitution.resolve(project)["slices"] or {}).values()
               for source in resolved["sources"]}
    # A slice she has not written yet has no file, so it is not in `allowed`; the
    # nine names are fixed (4.3), and one of them under this project is a rule.
    allowed |= {(paths.project_constitution(project) / f"{name}.md").resolve()
                for name in constitution.SLICE_NAMES}
    if wanted not in allowed:
        raise ConfigError(f"{path} is not one of this project's rule files, so nothing "
                          f"was written. The screen lists the files it can amend.")
    return wanted


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
    except ValueError:
        return False
    return True
