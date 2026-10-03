"""Connected services, as she sees them: three groups, each service's state in
words, and - for the chosen project - what Taller's work there may use.

Read from `connections` (one `claude mcp list` a minute); written through
`connections.allow`, which keeps each level in the project's own settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from taller import connections, notify

from . import reading, words

GROUPS = ("account", "plugin", "yours")


def page(project_name: str | None = None, *, search: dict[str, Any] | None = None,
         query: str = "") -> dict[str, Any]:
    names = [entry["name"] for entry in reading.project_entries() if entry.get("available")]
    chosen = project_name if project_name in names else (names[0] if names else "")
    allowed = connections.allowed(Path(reading.entry_for(chosen)["path"])) if chosen else {}
    by_group = connections.by_group()
    groups = []
    for key in GROUPS:
        shown, folded = [], []
        for service in by_group.get(key, []):
            if service["duplicate_of"]:
                continue                      # a plugin's repeat of one she has
            item = {"name": service["name"], "prefix": service["prefix"],
                    "state": service["state"],
                    "state_words": connections.STATE_WORDS[service["state"]],
                    "level": allowed.get(service["prefix"], "off")}
            (shown if service["state"] == "ok" else folded).append(item)
        sign_in = [i["name"] for i in folded if key == "account" and i["state"] == "sign_in"]
        others = [i for i in folded if i["name"] not in sign_in]
        groups.append({"key": key, "title": words.SERVICES["groups"][key], "shown": shown,
                       "sign_in": _joined(sign_in), "folded": others})
    return {"projects": names, "project": chosen, "groups": groups,
            "ready": connections.WORK_USE_READY,
            "problem": connections.problem(), "search": search, "query": query,
            "notify": {**notify.configured(), "problem": notify.last_problem(),
                       "example": words.SERVICES["notify_example"].format(
                           project=chosen or "Your project",
                           title="The list doesn't match")}}


def _joined(names: list[str]) -> str:
    if len(names) < 2:
        return "".join(names)
    return ", ".join(names[:-1]) + ", and " + names[-1]
