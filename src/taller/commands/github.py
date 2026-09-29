"""`taller github status|protect`: what GitHub says, and what to turn on there.

Read-only by design (spec 13, and the owner's decision of 2026-09-29): Taller
reports and prints; she is the one who changes a setting on her account.
"""

from __future__ import annotations

from typing import Any

from .. import github, issues, registry
from ..prompter import Prompter
from .common import project_path


def status(args: Any, prompter: Prompter) -> int:
    project = project_path(getattr(args, "path", None))
    entry = registry.get_project(project)
    repo = issues.repo_of(project)
    if repo is None:
        prompter.say(f"{entry['name']} has no GitHub remote, so there is nothing to check "
                     f"there. Everything Taller does works locally without one.")
        return 0
    ci = github.latest_ci(project, repo)
    rule = github.protection(repo)
    prompter.say("\n".join([
        f"{entry['name']} on {repo}",
        f"  checks: {ci['state']} - {ci['detail']}",
        f"  merging: {'protected' if rule['ok'] else 'not protected'} - {rule['detail']}",
        *([] if rule["ok"] else
          [f"  `taller github protect --path {project}` prints what to turn on."]),
    ]))
    return 0


def protect(args: Any, prompter: Prompter) -> int:
    project = project_path(getattr(args, "path", None))
    entry = registry.get_project(project)
    repo = issues.repo_of(project)
    if repo is None:
        prompter.say(f"{entry['name']} has no GitHub remote yet, so there is no branch to "
                     f"protect. Add one when you want the checks to run there.")
        return 0
    rule = github.protection(repo)
    if rule["ok"]:
        prompter.say(f"{repo} is already protected: {rule['detail']}.")
        return 0
    prompter.say(github.ruleset_instructions(repo))
    return 0
