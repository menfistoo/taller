"""`taller amend --reason TEXT [--path PROJECT]`: a rule change, made real.

Spec 9.8: a rule that is wrong is amended, never argued with at review. The
owner (or a chat, via `/taller:amend`) edits a rule file; this commits it and
refreshes every project the change reaches - spec 4.6: an amend to a shared
module writes to every project using it - and says which it touched.

Two places hold rules. The hub: `modules/`, `brands/`, `profiles/` and
`taller.yml` under `~/.taller`. A project: its `.taller/constitution/` files,
except the generated `00-index.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import generated, gitio, hub, paths, registry
from ..errors import ConfigError
from ..prompter import Prompter
from .common import project_path

HUB_RULES = ("modules", "brands", "profiles", "taller.yml")
PROJECT_RULES = ".taller/constitution/"
GENERATED = ".taller/constitution/00-index.md"


def run(args: Any, prompter: Prompter) -> int:
    hub_changes = _hub_changes()
    project, project_changes = _project_changes(getattr(args, "path", None))
    if not hub_changes and not project_changes:
        prompter.say("Nothing to amend: change a rule file first, then run this again.")
        return 0
    if project_changes:
        branch = gitio.git(project, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if branch != gitio.MAIN_BRANCH:
            raise ConfigError(f"{project} is on {branch}. A rule is amended on "
                              f"{gitio.MAIN_BRANCH}: switch to it, then run this again.")

    reason = (getattr(args, "reason", None) or "").strip()
    while not reason:
        reason = prompter.ask("amend.reason",
                              "  Why does the rule change? The reason is kept with it.").strip()

    lines: list[str] = []
    if hub_changes:
        hub.commit(f"amend: {reason}")
        touched = generated.refresh_for_hub_paths(hub_changes)
        lines.append(f"Amended the hub rules ({', '.join(hub_changes)}).")
        lines.extend(f"  refreshed {name} (sync: {sync})" for name, sync in touched)
        if not touched:
            lines.append("  No adopted project uses them yet.")
    if project_changes:
        gitio.git(project, "add", "--", *project_changes)
        gitio.git(project, "commit", "--quiet", "-m", f"amend: {reason}", "--",
                  *project_changes)
        name = registry.get_project(project)["name"]
        sync = generated.refresh(project)
        lines.append(f"Amended {name}'s rules ({', '.join(project_changes)}); "
                     f"refreshed {name} (sync: {sync}).")
    prompter.say("\n".join(lines))
    return 0


def _hub_changes() -> list[str]:
    root = paths.hub()
    if not (root / ".git").exists():
        return []
    return _changed(root, *HUB_RULES)


def _project_changes(given: str | None) -> tuple[Path | None, list[str]]:
    """The project's pending rule changes; none when it is not an adopted project."""
    project = project_path(given)
    if given is not None:
        entry = registry.get_project(project)          # a named project must be known
    else:
        try:
            entry = registry.get_project(project)
        except ConfigError:
            return None, []                             # standing somewhere else
    if not registry.is_adopted(entry):
        return None, []
    changed = [p for p in _changed(project, PROJECT_RULES) if p != GENERATED]
    return project, changed


def _changed(repo: Path, *where: str) -> list[str]:
    raw = gitio.git(repo, "-c", "core.quotepath=false", "status", "--porcelain", "-z",
                    "--untracked-files=all", "--no-renames", "--", *where,
                    check=False).stdout
    return sorted({entry[3:] for entry in raw.split("\0") if len(entry) > 3})
