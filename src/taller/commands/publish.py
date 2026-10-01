"""`taller publish`: send what waited, because the owner said so.

Nothing of hers leaves this machine on its own (`publish.automatic` is off): the
work is committed here, and this command is the moment it goes - the GitHub
issues that waited, the ones whose work finished, and `main`.
"""

from __future__ import annotations

from typing import Any

from .. import publishing, registry
from ..prompter import Prompter
from .common import project_path


def run(args: Any, prompter: Prompter) -> int:
    project = project_path(getattr(args, "path", None))
    name = registry.get_project(project)["name"]
    waiting = publishing.waiting(project)
    if not waiting["remote"]:
        prompter.say(f"{name} is only on this computer: there is nowhere to publish it to.")
        return 0
    if not waiting["held"]:
        prompter.say(f"Nothing to publish: everything of {name}'s is already at "
                     f"{waiting['remote']}.")
        return 0

    parts = []
    if waiting["commits"]:
        parts.append(f"{len(waiting['commits'])} change{'s' if len(waiting['commits']) != 1 else ''}")
    if waiting["tickets_without_issue"]:
        parts.append(f"{len(waiting['tickets_without_issue'])} new GitHub issue"
                     f"{'s' if len(waiting['tickets_without_issue']) != 1 else ''}")
    if waiting["issues_to_close"]:
        parts.append(f"{len(waiting['issues_to_close'])} finished issue"
                     f"{'s' if len(waiting['issues_to_close']) != 1 else ''} to close")
    prompter.say(f"Publishing {name} to {waiting['remote']}: {', '.join(parts)}.")

    sent = publishing.send(project)
    if sent["problem"]:
        prompter.say(f"  Not sent. {sent['problem']}")
        return 1
    prompter.say(f"  Sent. {name} is published.")
    return 0
