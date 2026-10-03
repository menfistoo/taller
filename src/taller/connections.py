"""Her connected services: listed, grouped, and said in words.

Read from `claude mcp list`, which health-checks every server - several seconds -
so the result is kept for a minute. Three groups: the services signed in through
her Claude account (`claude.ai …`), those a plugin brought (`plugin:<plugin>:<name>`),
and those she added herself. Taller holds no credential for any of them (spec
5.2): an account service is signed in on claude.ai, and used through it.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

from . import config, inference, locking, paths
from .errors import ConfigError

LIST_TIMEOUT = 60
KEEP_FOR = 60.0
STATE_WORDS = {"ok": "Connected", "sign_in": "Needs you to sign in",
               "broken": "Not working", "unset": "Not set up"}
LIST_FAILED = ("Taller could not read your connected services just now. "
               "Nothing has changed; try again in a minute.")
_LINE = re.compile(r"^(?P<name>.+?): (?P<target>.*?)(?: \(HTTP\))? - (?P<status>.+)$")
_ACCOUNT = "claude.ai "

_cache: dict[str, Any] = {"at": 0.0, "found": None, "problem": ""}


def listed() -> list[dict[str, Any]]:
    """Every service, in the order the CLI lists them. Empty, with `problem()`
    saying why, when the list could not be read."""
    if _cache["found"] is not None and time.monotonic() - _cache["at"] < KEEP_FOR:
        return _cache["found"]
    try:
        done = _run_list()
    except (OSError, subprocess.SubprocessError):
        done = None
    if done is None or done.returncode != 0:
        found, problem = [], LIST_FAILED
    else:
        found, problem = _parse(done.stdout), ""
    _cache.update(at=time.monotonic(), found=found, problem=problem)
    return found


def by_group() -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {"account": [], "plugin": [], "yours": []}
    for service in listed():
        groups[service["group"]].append(service)
    return groups


def problem() -> str:
    """Why the last read found nothing, or ''."""
    return str(_cache["problem"])


def forget() -> None:
    """Read again next time - after a service is added, say."""
    _cache.update(at=0.0, found=None, problem="")


# --- what each project's work may use ------------------------------------------

# Letting Taller's work use her services is built but not yet proven on her own
# accounts: a service's sign-in inside a job failed in the live check
# (2026-10-01), and she chose to prove it as its own step. Until then nothing is
# handed to any job, and the page says so. Turned on in code once proven.
WORK_USE_READY = False
NOT_READY = ("Letting Taller's work use your services isn't ready yet, so for now none "
             "of them is used.")

LEVELS = ("off", "look", "look_and_add")
# A tool is allowed by its exact name: the live check (2026-10-01) showed the CLI
# does not honour an allowance by the start of a name. In unattended mode what is
# not allowed is refused, and a refusal beats an allowance. A tool is judged by
# the words of its name (split on _ and -), closed rather than open: a reading
# tool's name starts with a reading word, an adding one with an adding word, and
# a name with any word that begins like one below is refused at every level.
READ_VERBS = ("search", "get", "list", "read", "fetch", "view", "find")
ADD_VERBS = ("create", "add")
NEVER_STEMS = ("send", "sent", "delet", "remov", "trash", "shar", "forward", "repl", "updat",
               "invit", "attende", "guest", "permission", "collaborat", "publish", "archiv",
               "renam", "upload", "mark", "label", "merg", "edit", "assign", "transfer",
               "spam", "pay", "charg", "refund", "approv", "accept", "declin", "cancel",
               "rsvp", "modif", "patch", "set", "move", "clos", "complet", "unsubscrib")
# What an adding tool may not add: things that reach other people.
ADD_REFUSED = ("messag", "email", "mail", "comment", "post", "chat", "channel", "user",
               "member", "team", "issue", "pull", "event", "meeting")
LEARN_TIMEOUT = 120
_PREFIX = re.compile(r"^[a-z0-9_]+$")


def allowed(project: Path | str) -> dict[str, str]:
    """service prefix -> level, for the services this project's work may use."""
    return _levels(config.read_project_config(Path(project)).get("services"))


def _levels(given: Any) -> dict[str, str]:
    """A `services` setting read safely: anything but a map of levels is nothing."""
    if not isinstance(given, Mapping):
        return {}
    return {str(name): str(level) for name, level in given.items() if level in LEVELS[1:]}


def name_words(name: str) -> list[str]:
    """`add-tasks` and `add_tasks` are the same two words."""
    return [word for word in re.split(r"[_\-\s]+", name.lower()) if word]


def allow(project: Path | str, service: str, level: str) -> list[str]:
    """Set one service's level for this project, in its own settings."""
    from . import settings

    if level not in LEVELS:
        raise ConfigError(f"{level!r} is not a level; the levels are {', '.join(LEVELS)}.")
    if not _PREFIX.match(service):
        raise ConfigError(f"{service!r} is not a service Taller knows.")
    if level != "off" and not WORK_USE_READY:
        raise ConfigError(NOT_READY)
    if level != "off" and known_tools(service) is None:
        found = present().get(service)
        learned = _learn_run(service, _server(found["target"])) \
            if found and found["target"] else None
        if not learned:
            raise ConfigError(LEARN_FAILED)
        names = [tool.split("__", 2)[2] for tool in learned
                 if tool.startswith(f"mcp__{service}__")]
        locking.atomic_write_text(tools_file(service), json.dumps({"tools": sorted(names)}))
    settings.set_value(f"services.{service}", json.dumps(level), Path(project))
    return [f"{service}: {level}"]


LEARN_FAILED = ("Taller could not reach that service just now, so it is still off. "
                "Check it is connected, then try again.")


def tools_file(service: str) -> Path:
    """What Taller learned a service can do. On this machine only: tool names are
    the service's, not hers, and another machine learns them again."""
    return paths.run_dir() / "services" / f"{service}.json"


def known_tools(service: str) -> list[str] | None:
    try:
        return list(json.loads(tools_file(service).read_text(encoding="utf-8"))["tools"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _judged(names: list[str], level: str) -> tuple[list[str], list[str]]:
    """(allowed, refused) tool names for a level, by the words of each name."""
    allowed, refused = [], []
    for name in names:
        words = name_words(name)
        never = any(word.startswith(NEVER_STEMS) for word in words)
        reads = bool(words) and words[0] in READ_VERBS \
            and not any(word in ADD_VERBS for word in words)
        adds = level == "look_and_add" and bool(words) and words[0] in ADD_VERBS \
            and not any(word.startswith(ADD_REFUSED) for word in words)
        (allowed if not never and (reads or adds) else refused).append(name)
    return allowed, refused


def present() -> dict[str, dict[str, Any]]:
    """Her connected services by the name a job knows them by - the first that is
    connected, so a plugin's unconfigured repeat never hides the real one."""
    found: dict[str, dict[str, Any]] = {}
    for service in listed():
        if service["state"] == "ok" and service["target"] \
                and service["prefix"] not in found:
            found[service["prefix"]] = service
    return found


def _learn_run(service: str, server: dict[str, Any]) -> list[str] | None:
    """One small request with only this service loaded, to read the tools it
    offers from the CLI's start-up event. None when it could not be read."""
    import os

    claude = shutil.which("claude") or "claude"
    env = {k: v for k, v in os.environ.items() if k not in set(inference.HOST_SESSION)}
    argv = [claude, "-p", "--model", "haiku", "--effort", "low", "--output-format",
            "stream-json", "--verbose", "--permission-mode", "dontAsk", "--strict-mcp-config",
            "--mcp-config",
            json.dumps({"mcpServers": {service: server}})]
    cwd = paths.scratch_cwd()
    cwd.mkdir(parents=True, exist_ok=True)
    try:
        done = subprocess.run(argv, input="Reply with the single word OK.",
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, cwd=str(cwd), timeout=LEARN_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in done.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            tools = [t for t in event.get("tools") or [] if t.startswith(f"mcp__{service}__")]
            return tools or None
    return None


def for_dispatch(cfg: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    """(the --mcp-config, tools to allow, tools to refuse) for a job whose project
    allows services. A service gone from her list is left out; the work goes on."""
    wanted = _levels(cfg.get("services")) if WORK_USE_READY else {}
    if not wanted:
        return None, [], []
    connected = present()
    servers: dict[str, Any] = {}
    allow_tools: list[str] = []
    deny_tools: list[str] = []
    for prefix, level in sorted(wanted.items()):
        service = connected.get(prefix)
        names = known_tools(prefix)
        if not service or not names:
            continue                         # gone, signed out, or not learned: left out
        servers[prefix] = _server(service["target"])
        allowed_names, refused_names = _judged(names, level)
        allow_tools += [f"mcp__{prefix}__{name}" for name in allowed_names]
        deny_tools += [f"mcp__{prefix}__{name}" for name in refused_names]
    if not servers:
        return None, [], []
    return {"mcpServers": servers}, allow_tools, deny_tools


def _server(target: str) -> dict[str, Any]:
    if target.startswith(("http://", "https://")):
        return {"type": "http", "url": target}
    parts = [part.strip('"') for part in shlex.split(target, posix=False)]
    return {"command": parts[0], "args": parts[1:]}


def prefix_of(name: str) -> str:
    """The name a job knows a service by: `Google Drive` -> `google_drive`."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _run_list() -> subprocess.CompletedProcess:
    """`claude mcp list`, without the host session's variables (as a dispatch)."""
    import os

    claude = shutil.which("claude") or "claude"
    env = {k: v for k, v in os.environ.items() if k not in set(inference.HOST_SESSION)}
    return subprocess.run([claude, "mcp", "list"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env,
                          timeout=LIST_TIMEOUT)


def _parse(text: str) -> list[dict[str, Any]]:
    found = []
    for line in text.splitlines():
        match = _LINE.match(line.strip())
        if not match:
            continue
        raw = match["name"]
        if raw.startswith(_ACCOUNT):
            group, name, made_by = "account", raw[len(_ACCOUNT):], "your Claude account"
        elif raw.startswith("plugin:") and raw.count(":") >= 2:
            _, made_by, name = raw.split(":", 2)
            group = "plugin"
        else:
            group, name, made_by = "yours", raw, "you"
        found.append({"name": name, "group": group, "state": _state(match["status"]),
                      "made_by": made_by, "prefix": prefix_of(name),
                      "target": match["target"].strip(), "duplicate_of": None})
    connected = {s["name"].lower(): s["name"] for s in found if s["state"] == "ok"}
    for service in found:
        # A connected service never repeats itself, so only an unset entry can.
        if service["state"] == "unset":
            service["duplicate_of"] = connected.get(service["name"].lower())
    return found


def _state(status: str) -> str:
    status = status.lower()
    if "connected" in status and "failed" not in status:
        return "ok"
    if "authentication" in status or "sign in" in status:
        return "sign_in"
    if "not configured" in status:
        return "unset"
    return "broken"


# --- adding a service from the public catalogue --------------------------------

CATALOGUE = "https://registry.modelcontextprotocol.io/v0/servers"
CATALOGUE_TIMEOUT = 30
# Makers she would know, by the exact namespace their entries are published
# under (`com.stripe/mcp` is Stripe's) - exact, so `xyz.google` is not Google.
KNOWN_MAKERS = {"com.google": "Google", "com.microsoft": "Microsoft",
                "com.atlassian": "Atlassian", "com.notion": "Notion", "com.slack": "Slack",
                "com.todoist": "Todoist", "app.linear": "Linear", "com.figma": "Figma",
                "com.cloudflare": "Cloudflare", "com.stripe": "Stripe",
                "com.github": "GitHub", "com.anthropic": "Anthropic",
                "io.github.github": "GitHub", "io.github.stripe": "Stripe",
                "io.github.cloudflare": "Cloudflare", "io.github.microsoft": "Microsoft",
                "io.github.anthropics": "Anthropic", "io.github.doist": "Todoist",
                "io.github.makenotion": "Notion", "io.github.atlassian": "Atlassian"}
SEARCH_FAILED = "The catalogue could not be searched just now. Try again in a minute."
A_PERSON_ON_GITHUB = "a person on GitHub"


def search(query: str) -> dict[str, Any]:
    """The catalogue's answer to her words: known makers first, the rest apart."""
    query = " ".join(str(query).split())[:80]
    if not query:
        return {"known": [], "others": [], "problem": ""}
    answer = _catalogue(query)
    if answer is None:
        return {"known": [], "others": [], "problem": SEARCH_FAILED}
    found, seen = [], set()
    for item in answer.get("servers") or []:
        if not isinstance(item, dict):
            continue
        entry = _entry(item.get("server", item))
        if entry["addable"] and entry["name"] not in seen:     # one line per service,
            seen.add(entry["name"])                             # not one per version
            found.append(entry)
    return {"known": [e for e in found if e["known"]],
            "others": [e for e in found if not e["known"]], "problem": ""}


def entry_named(name: str) -> dict[str, Any] | None:
    """One catalogue entry, read again from the catalogue - never from a form."""
    answer = _catalogue(name)
    if answer is None:
        return None
    for item in answer.get("servers") or []:
        server = item.get("server", item) if isinstance(item, dict) else {}
        if server.get("name") == name:
            return _entry(server)
    return None


def add(name: str) -> list[str]:
    """Add one catalogue entry to Claude, for every project on this computer to be
    allowed - each one still Not used until she says otherwise."""
    entry = entry_named(name)
    if entry is None or not entry["addable"]:
        raise ConfigError("That service could not be found in the catalogue any more, "
                          "so nothing was added.")
    argv = ["mcp", "add", "--scope", "user"]
    if entry["url"]:
        argv += ["--transport", "http", entry["prefix"], entry["url"]]
    else:
        argv += [entry["prefix"], "--", "npx", "-y", entry["package"]]
    done = _run_add(argv)
    forget()
    if done.returncode != 0:
        raise ConfigError(f"{entry['title']} could not be added; nothing was changed.")
    return [f"{entry['title']} was added. It is not used by any project until you choose."]


def _entry(server: Mapping[str, Any]) -> dict[str, Any]:
    name = str(server.get("name") or "")
    namespace = name.split("/", 1)[0].lower()
    known = namespace in KNOWN_MAKERS
    maker = KNOWN_MAKERS.get(namespace) or (
        A_PERSON_ON_GITHUB if namespace.startswith("io.github.")
        else ".".join(reversed(namespace.split("."))))
    url = next((str(remote.get("url")) for remote in server.get("remotes") or []
                if str(remote.get("type", "")).endswith("http")
                and str(remote.get("url") or "").startswith("https://")), "")
    package = next((pkg.get("identifier") for pkg in server.get("packages") or []
                    if pkg.get("registryType") == "npm" and pkg.get("identifier")), "")
    # Untitled: a maker she knows is named by the maker ("com.stripe/mcp" is
    # Stripe's), anyone else by the last part of the entry's name.
    title = str(server.get("title") or (maker if known else "")
                or name.rsplit("/", 1)[-1] or name)
    return {"name": name, "title": title, "description": str(server.get("description") or ""),
            "maker": maker, "known": known, "url": url, "package": package,
            "prefix": prefix_of(title),
            "addable": bool(name and prefix_of(title) and (url or package))}


def _catalogue(query: str) -> dict[str, Any] | None:
    """The catalogue's answer, asked twice: measured, its first answer of the day
    can take longer than a reasonable wait. None when it does not answer."""
    for _ in range(2):
        try:
            return _fetch_catalogue(query)
        except (OSError, ValueError):
            continue
    return None


def _fetch_catalogue(query: str) -> dict[str, Any]:
    import urllib.parse
    import urllib.request

    address = f"{CATALOGUE}?{urllib.parse.urlencode({'search': query, 'limit': 30})}"
    with urllib.request.urlopen(address, timeout=CATALOGUE_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _run_add(argv: list[str]) -> subprocess.CompletedProcess:
    import os

    claude = shutil.which("claude") or "claude"
    env = {k: v for k, v in os.environ.items() if k not in set(inference.HOST_SESSION)}
    return subprocess.run([claude, *argv], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=LIST_TIMEOUT)
