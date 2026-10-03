"""Telling her when something needs her, through a service she chose.

Off until she chooses (`notify.channel`): a task in her Todoist, or a note on her
calendar - notes to herself; Taller never sends anything to anyone. One small
`notifier` job is allowed exactly one tool of that service, with words fixed
here. A moment is told once (`notified` in status.yml, written whether or not
the notice went), and a notice that fails is recorded and shown on the services
page: it never blocks, retries or delays the work.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from . import config, connections, inference, locking, paths, registry, settings, tickets
from .errors import ConfigError

# channel -> (the service it uses, the words a fitting tool's name has)
CHANNELS = {"todoist": ("todoist", ({"add", "create"}, {"task", "tasks"})),
            "calendar": ("google_calendar", ({"create", "add"}, {"event", "events"}))}
MOMENTS = ("needs_you", "stopped")
NOTICE = {"needs_you": '{project}: "{title}" is ready for you to look at. {link}',
          "stopped": '{project}: "{title}" has stopped and needs you. {link}'}
NOT_AVAILABLE = ("Taller could not use {service} for your notice. Check it is connected on "
                 "Connected services, and let a project use it once so Taller learns it.")
SIGNED_OUT = "Your {service} needs you to sign in again, so the notice was not added."
NOT_ADDED = "Your last notice could not be added."
ADDED_SCHEMA = {"type": "object", "properties": {"added": {"type": "boolean"}},
                "required": ["added"], "additionalProperties": True}
NOTIFY_TIMEOUT = 120


def configured() -> dict[str, Any]:
    given = config.load_hub_config().get("notify") or {}
    return {"channel": given.get("channel") if given.get("channel") in CHANNELS else None,
            "when": [w for w in (given.get("when") or []) if w in MOMENTS]}


def choose(channel: str | None, when: list[str]) -> list[str]:
    """Her choice, in the hub: one channel or none, and which moments to tell."""
    chosen = channel if channel in CHANNELS else None
    if chosen and not connections.WORK_USE_READY:
        raise ConfigError(connections.NOT_READY)
    moments = [moment for moment in MOMENTS if moment in when]
    settings.set_value("notify", json.dumps({"channel": chosen, "when": moments}))
    return ["Saved."]


def notice(project_name: str, ticket: Mapping[str, Any], why: str) -> str:
    from .commands.cockpit import DEFAULT_PORT

    link = f"http://127.0.0.1:{DEFAULT_PORT}/thing/{project_name}/{int(ticket['id'])}"
    return NOTICE[why].format(project=project_name, title=ticket["title"], link=link)


def tell(project_name: str, ticket: Mapping[str, Any], why: str) -> dict[str, Any]:
    """One notice for this moment, if she asked for one and it was not told before."""
    chosen = configured()
    if chosen["channel"] is None or why not in chosen["when"] \
            or not connections.WORK_USE_READY:
        return {"sent": False, "problem": ""}
    moment = f"{why}:{ticket.get('stage')}"
    if moment in (ticket.get("notified") or {}):
        return {"sent": False, "problem": ""}
    service, (verbs, things) = CHANNELS[chosen["channel"]]
    _remember(project_name, int(ticket["id"]), moment)
    named = service.replace("_", " ").title()
    tool = next((name for name in connections.known_tools(service) or []
                 if set(connections.name_words(name)) & verbs
                 and set(connections.name_words(name)) & things), None)
    listed = next((s for s in connections.listed() if s["prefix"] == service
                   and s["target"]), None)
    if listed is not None and listed["state"] == "sign_in":
        return _failed(SIGNED_OUT.format(service=named))
    connected = connections.present().get(service)
    if tool is None or connected is None:
        return _failed(NOT_AVAILABLE.format(service=named))
    dispatch = inference.Dispatch(
        role="notifier", config=config.load_hub_config(), timeout=NOTIFY_TIMEOUT,
        schema=ADDED_SCHEMA,
        prompt=("Use your one tool once, to add a note for me with exactly this text and "
                "nothing else. Add no guests, attendees or recipients of any kind. Then "
                "answer whether it was added.\n\n"
                f"{notice(project_name, ticket, why)}\n"),
        services=({"mcpServers": {service: connections._server(connected["target"])}},
                  [f"mcp__{service}__{tool}"]))
    try:
        result = inference.infer(dispatch)
    except Exception:                         # a notice never stops the work
        return _failed(NOT_ADDED)
    if not result.ok or not isinstance(result.value, Mapping) \
            or result.value.get("added") is not True:
        return _failed(NOT_ADDED)
    return {"sent": True, "problem": ""}


def last_problem() -> str:
    try:
        return str(json.loads(_problem_file().read_text(encoding="utf-8"))["problem"])
    except (OSError, ValueError, KeyError):
        return ""


def _failed(problem: str) -> dict[str, Any]:
    locking.atomic_write_text(_problem_file(), json.dumps(
        {"problem": problem, "at": datetime.now().isoformat(timespec="seconds")}))
    return {"sent": False, "problem": problem}


def _problem_file() -> Path:
    return paths.run_dir() / "notify.json"


def _remember(project_name: str, ticket_id: int, moment: str) -> None:
    """Written before the notice is tried: a moment is told at most once."""
    entry = next(e for e in registry.list_projects() if e["name"] == project_name)
    project = Path(entry["path"])
    ticket = tickets.load(project, ticket_id)
    ticket["notified"] = {**(ticket.get("notified") or {}),
                          moment: datetime.now().isoformat(timespec="seconds")}
    tickets.write(project, ticket, f"ticket {ticket_id:04d}: told you", retry_issue=False)
