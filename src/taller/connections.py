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

# Letting Taller's work use her services. Proved on her own accounts on
# 2026-10-03 - Drive 'May look' reached through her setup, a Todoist notice
# added - and switched on with her say-so. Turning it off hands nothing to any
# job, and the page says so.
WORK_USE_READY = True
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


def tool_prefix(listed_name: str) -> str:
    """What a service's tools are called inside a job, from its name in her list:
    `claude.ai Google Drive` -> `claude_ai_Google_Drive` (its tools are
    `mcp__claude_ai_Google_Drive__<tool>`)."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", listed_name)


def allowed(project: Path | str) -> dict[str, str]:
    """service prefix -> level, for the services this project's work may use."""
    return _levels(_choices().get(_name_of(project)))


def choices_file() -> Path:
    """Each project's service levels - on this computer only, never in a project's
    own files, which are published with it (her choice, 2026-10-03)."""
    return paths.run_dir() / "services" / "projects.json"


def _choices() -> dict[str, Any]:
    try:
        found = json.loads(choices_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _name_of(project: Path | str) -> str:
    from . import registry

    return str(registry.get_project(Path(project))["name"])


def _levels(given: Any) -> dict[str, str]:
    """A `services` setting read safely: anything but a map of levels is nothing."""
    if not isinstance(given, Mapping):
        return {}
    return {str(name): str(level) for name, level in given.items() if level in LEVELS[1:]}


def name_words(name: str) -> list[str]:
    """`add-tasks` and `add_tasks` are the same two words."""
    return [word for word in re.split(r"[_\-\s]+", name.lower()) if word]


def allow(project: Path | str, service: str, level: str) -> list[str]:
    """Set one service's level for this project, on this computer."""
    if level not in LEVELS:
        raise ConfigError(f"{level!r} is not a level; the levels are {', '.join(LEVELS)}.")
    if not _PREFIX.match(service):
        raise ConfigError(f"{service!r} is not a service Taller knows.")
    if level != "off" and not WORK_USE_READY:
        raise ConfigError(NOT_READY)
    if level != "off" and known_tools(service) is None:
        learned = _learn_run(service) if service in present() else None
        if not learned:
            raise ConfigError(LEARN_FAILED)
        locking.atomic_write_text(tools_file(service), json.dumps({"tools": sorted(learned)}))
    name = _name_of(project)
    with locking.file_lock(choices_file().with_suffix(".lock")):
        everything = _choices()
        mine = {k: v for k, v in _levels(everything.get(name)).items() if k != service}
        if level != "off":
            mine[service] = level
        everything[name] = mine
        locking.atomic_write_text(choices_file(), json.dumps(everything, indent=1,
                                                             sort_keys=True))
    return [f"{service}: {level}"]


# A job with her setup loaded may always load a tool and give its answer: these
# two are Claude Code's own plumbing, never refused.
KEEP_TOOLS = ("ToolSearch", "StructuredOutput")


def setup_tools_file() -> Path:
    """The tools her setup offers besides services, as last seen while learning."""
    return paths.run_dir() / "services" / "_setup.json"


def setup_tools() -> list[str]:
    try:
        return list(json.loads(setup_tools_file().read_text(encoding="utf-8"))["tools"])
    except (OSError, ValueError, KeyError, TypeError):
        return []


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


def _learn_run(service: str) -> list[str] | None:
    """One small request with her setup loaded as a job with services loads it, to
    read the names of the tools this service offers from the CLI's start-up event.
    None when it could not be read."""
    import os

    found = present().get(service)
    if found is None:
        return None
    claude = shutil.which("claude") or "claude"
    env = {k: v for k, v in os.environ.items() if k not in set(inference.HOST_SESSION)}
    argv = [claude, "-p", "--model", "haiku", "--effort", "low", "--output-format",
            "stream-json", "--verbose", "--permission-mode", "dontAsk"]
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
            own = f"mcp__{tool_prefix(found['raw'])}__"
            offered = event.get("tools") or []
            locking.atomic_write_text(setup_tools_file(), json.dumps(
                {"tools": sorted(t for t in offered if not t.startswith("mcp__"))}))
            tools = [t[len(own):] for t in event.get("tools") or [] if t.startswith(own)]
            return tools or None
    return None


def for_dispatch(cfg: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """(tools to allow, tools to refuse) for a job whose project allows services.
    Empty when it allows none that is connected and learned here - a service gone
    from her list, or signed out, is left out and the work goes on."""
    project = (cfg.get("project") or {}).get("name")
    wanted = _levels(_choices().get(project)) if WORK_USE_READY and project else {}
    if not wanted:
        return [], []
    connected = present()
    allow_tools: list[str] = []
    deny_tools: list[str] = []
    for service, level in sorted(wanted.items()):
        found = connected.get(service)
        names = known_tools(service)
        if not found or not names:
            continue
        own = tool_prefix(found["raw"])
        allowed_names, refused_names = _judged(names, level)
        allow_tools += [f"mcp__{own}__{name}" for name in allowed_names]
        deny_tools += [f"mcp__{own}__{name}" for name in refused_names]
    if not allow_tools:
        return [], []
    return allow_tools, deny_tools + refuse_others(allow_tools)


def refuse_others(allowed_tools: list[str]) -> list[str]:
    """Every other service in her list, refused whole by name: her setup loads in
    a job with services, and only what was allowed may be used."""
    keep = {tool.split("__")[1] for tool in allowed_tools if tool.count("__") >= 2}
    return [f"mcp__{prefix}__*" for prefix in
            dict.fromkeys(tool_prefix(service["raw"]) for service in listed())
            if prefix not in keep]


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
        found.append({"name": name, "raw": raw, "group": group,
                      "state": _state(match["status"]),
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
