"""The smoke gate: the application boots and the change renders (spec 9.6).

Stage 6 only. `http` boots the app on a port allocated here - never a fixed one,
so two tickets and the owner's own dev server never collide - with a copy of
the database, polls until it answers 200, then GETs every configured route and
every route mapped from a changed template. The boot process tree is ended in a
`finally`, whatever happened.

A 200 with a non-empty body is required: a login redirect or an empty page
would pass a naive check while rendering nothing (`smoke.not-rendered`).
"""

from __future__ import annotations

import base64
import os
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from taller import inference
from taller.gates import Finding, Verdict, finding, verdict
from taller.gates import tests as tests_gate

GATE = "smoke"
POLL_S = 0.2
REQUEST_TIMEOUT_S = 15
TAIL_LINES = 30
TEMPLATE_SUFFIXES = (".html", ".htm", ".j2", ".jinja", ".jinja2")


def run(worktree: Path | str, ruleset: Mapping[str, Any], *,
        templates: Mapping[str, list[str]] | None = None,
        changed: Sequence[str] = ()) -> Verdict:
    """`templates`: the explorer's template -> routes map; `changed`: the diff's paths."""
    worktree = Path(worktree)
    config = ruleset.get("smoke")
    if not isinstance(config, Mapping) or not config.get("kind"):
        return _error("No `smoke` configuration: the profile or taller.yml must declare "
                      "one, even if it is `kind: none` (spec 9.6).")
    kind = config["kind"]
    if kind == "none":
        return verdict(GATE, [], {"skipped": True})
    if kind == "import":
        return _import(worktree, config)
    if kind != "http":
        return _error(f"Unknown smoke kind {kind!r}: use http, import or none.")
    return _http(worktree, config, templates or {}, changed)


# --- http ------------------------------------------------------------------------------

def _http(worktree: Path, config: Mapping[str, Any], templates: Mapping[str, list[str]],
          changed: Sequence[str]) -> Verdict:
    findings: list[Finding] = []
    routes = [str(route) for route in config.get("routes") or ["/"]]
    for path in changed:
        if not path.lower().endswith(TEMPLATE_SUFFIXES):
            continue
        mapped = [str(route) for route in templates.get(path) or []]
        if not mapped:
            findings.append(finding(
                "smoke.unmapped-template", path, 0,
                f"No route is known to render {path}, so smoke could not exercise it.",
                "Check it by hand; the gate fell back to the configured routes."))
        routes.extend(route for route in mapped if route not in routes)

    timeout_s = float(config.get("timeout_s") or 30)
    port = _free_port()
    data_dir = Path(tempfile.mkdtemp(prefix="taller-smoke-"))
    values = {"TALLER_SMOKE_PORT": str(port), "TALLER_SMOKE_DATA": str(data_dir),
              "TALLER_SMOKE_SECRET": os.environ.get("TALLER_SMOKE_SECRET", "")}
    metrics: dict[str, Any] = {"port": port, "routes_checked": []}
    process: subprocess.Popen | None = None
    log_path = data_dir.parent / f"{data_dir.name}.log"
    try:
        error = _prepare_data(worktree, config, data_dir)
        if error:
            return _error(error, metrics)
        ready = str(config.get("ready") or "auto")
        ready = f"http://127.0.0.1:{port}/" if ready == "auto" else _substitute(ready, values)
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
               **{str(k): _substitute(str(v), values)
                  for k, v in (config.get("env") or {}).items()}}
        argv = _argv(_substitute(str(config.get("boot") or ""), values), worktree)
        if not argv:
            return _error("`smoke.boot` is empty: nothing to start.", metrics)
        with open(log_path, "wb") as log:
            try:
                process = subprocess.Popen(argv, cwd=str(worktree), env=env,
                                           stdin=subprocess.DEVNULL, stdout=log,
                                           stderr=subprocess.STDOUT, **_new_group())
            except OSError as exc:
                findings.append(finding("smoke.boot-failed", "", 0,
                                        f"`{config.get('boot')}` could not start: {exc}"))
                return verdict(GATE, findings, metrics)

            started = time.monotonic()
            state = _wait_ready(process, ready, started + timeout_s, config, values)
            metrics["boot_s"] = round(time.monotonic() - started, 2)
            if state == "exited":
                findings.append(finding(
                    "smoke.boot-failed", "", 0,
                    f"The app exited with code {process.returncode} before it answered:\n"
                    f"{_tail(log_path)}",
                    "Run the boot command by hand and read the error."))
                return verdict(GATE, findings, metrics)
            if state == "timeout":
                findings.append(finding(
                    "smoke.timeout", "", 0,
                    f"The app did not answer 200 at {ready} within {timeout_s:g} s.\n"
                    f"{_tail(log_path)}", None))
                return verdict(GATE, findings, metrics)

            base = f"http://127.0.0.1:{port}"
            for route in routes:
                metrics["routes_checked"].append(route)
                found = _check(base + route, route, config, values)
                if found:
                    findings.append(found)
        return verdict(GATE, findings, metrics)
    finally:
        if process is not None and process.poll() is None:
            inference._kill_tree(process)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        shutil.rmtree(data_dir, ignore_errors=True)
        try:
            log_path.unlink(missing_ok=True)
        except OSError:
            pass


def _wait_ready(process: subprocess.Popen, url: str, deadline: float,
                config: Mapping[str, Any], values: Mapping[str, str]) -> str:
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return "exited"
        try:
            status, _, _ = _get(url, config, values, timeout=2)
            if status == 200:
                return "ready"
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(POLL_S)
    return "exited" if process.poll() is not None else "timeout"


def _check(url: str, route: str, config: Mapping[str, Any],
           values: Mapping[str, str]) -> Finding | None:
    try:
        status, location, body = _get(url, config, values, timeout=REQUEST_TIMEOUT_S)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return finding("smoke.route-error", "", 0, f"GET {route} failed: {exc}",
                       "The route must answer; read the app's error for this path.")
    if status >= 500:
        return finding("smoke.route-error", "", 0, f"GET {route} answered {status}.",
                       "The route raised; read the app's error for this path.")
    if 300 <= status < 400:
        return finding("smoke.not-rendered", "", 0,
                       f"GET {route} redirected to {location or '?'} instead of rendering.",
                       "Configure `smoke.auth` so the gate can reach the page.")
    if status != 200:
        return finding("smoke.not-rendered", "", 0, f"GET {route} answered {status}.", None)
    if not body.strip():
        return finding("smoke.not-rendered", "", 0, f"GET {route} answered 200 with an "
                       "empty body.", None)
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _get(url: str, config: Mapping[str, Any], values: Mapping[str, str], *,
         timeout: float) -> tuple[int, str, bytes]:
    """(status, Location, body). Redirects are followed only when `auth` is set."""
    auth = config.get("auth") if isinstance(config.get("auth"), Mapping) else None
    request = urllib.request.Request(url)
    handlers: list[Any] = [urllib.request.ProxyHandler({})]
    if auth and auth.get("kind") == "basic":
        user = _substitute(str(auth.get("user") or ""), values)
        secret = _substitute(str(auth.get("secret") or ""), values)
        token = base64.b64encode(f"{user}:{secret}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    else:
        handlers.append(_NoRedirect())
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.headers.get("Location", ""), response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp else b""
        return exc.code, exc.headers.get("Location", "") if exc.headers else "", body


# --- import ------------------------------------------------------------------------------

def _import(worktree: Path, config: Mapping[str, Any]) -> Verdict:
    module = str(config.get("module") or "")
    if not module:
        return _error("`smoke.module` is not set for `kind: import`.")
    python = tests_gate.interpreter(worktree)
    if not Path(python).is_file():
        return _error(python)
    timeout_s = float(config.get("timeout_s") or 30)
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        completed = inference._run_bounded([python, "-c", f"import {module}"], input="",
                                           encoding="utf-8", errors="replace",
                                           cwd=str(worktree), timeout=timeout_s, env=env)
    except subprocess.TimeoutExpired:
        return verdict(GATE, [finding("smoke.timeout", "", 0,
                                      f"Importing {module} took over {timeout_s:g} s.")], {})
    if completed.returncode == 0:
        return verdict(GATE, [], {"module": module})
    output = (completed.stderr or "") + (completed.stdout or "")
    tail = "\n".join(output.strip().splitlines()[-TAIL_LINES:])
    return verdict(GATE, [finding("smoke.boot-failed", "", 0,
                                  f"Importing {module} raised:\n{tail}")], {"module": module})


# --- helpers -------------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _prepare_data(worktree: Path, config: Mapping[str, Any], data_dir: Path) -> str | None:
    """`copy` copies the live database file only - never its -wal or -shm."""
    mode = str(config.get("data") or "none")
    if mode in ("none", "fresh"):
        return None
    if mode != "copy":
        return f"Unknown smoke data mode {mode!r}: use copy, fresh or none."
    source = config.get("database")
    if not source:
        return "`smoke.data: copy` needs `smoke.database`: the project database to copy."
    live = worktree / str(source)
    if live.is_file():
        shutil.copyfile(live, data_dir / live.name)
    return None


def _substitute(text: str, values: Mapping[str, str]) -> str:
    for key, value in values.items():
        text = text.replace(f"${key}", value).replace(f"${{{key}}}", value)
    return text


def _argv(command: str, worktree: Path) -> list[str]:
    """`python ...` runs under the interpreter the tests gate would use."""
    argv = shlex.split(command, posix=os.name != "nt")
    argv = [part.strip('"') for part in argv] if os.name == "nt" else argv
    if argv and argv[0] in ("python", "python3", "py"):
        python = tests_gate.interpreter(worktree)
        argv[0] = python if Path(python).is_file() else argv[0]
    return argv


def _new_group() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _tail(path: Path) -> str:
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.strip().splitlines()[-TAIL_LINES:])


def _error(message: str, metrics: dict[str, Any] | None = None) -> Verdict:
    return {"gate": GATE, "result": "error", "findings": [], "metrics": metrics or {},
            "error": message}
