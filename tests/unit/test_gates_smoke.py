"""The smoke gate: the application boots and the change renders. Spec 9.6, 15.1.

Each test writes a tiny stdlib server whose behaviour is chosen by `MODE`, so the
gate is exercised against real processes and real HTTP, never a mock.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import support
from taller import constitution
from taller.gates import smoke

SERVER = '''
import http.server, os, subprocess, sys, time

mode = os.environ.get("MODE", "ok")
log = os.environ.get("HITS")
if mode == "crash":
    sys.stderr.write("Traceback: the app could not start\\n")
    sys.exit(3)
if mode == "hang":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    open(os.environ["CHILD_PID"], "w").write(str(child.pid))
    time.sleep(600)
if mode == "db":
    database = os.environ["DATABASE"]
    assert os.path.dirname(os.path.abspath(database)) == os.path.abspath(os.environ["DATA_DIR"])
    assert not os.path.exists(database + "-wal") and not os.path.exists(database + "-shm")
    with open(database, "ab") as handle:
        handle.write(b"written by the smoke run")

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if log:
            with open(log, "a") as handle:
                handle.write(self.path + "\\n")
        if self.path == "/broken":
            return self.answer(500, b"boom")
        if self.path == "/private":
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return
        if self.path == "/empty":
            return self.answer(200, b"")
        return self.answer(200, ("port " + os.environ["PORT"]).encode())

    def answer(self, code, body):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

http.server.HTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
'''


def app(tmp_path: Path, mode: str = "ok", **extra) -> tuple[Path, dict]:
    root = tmp_path / "app"
    support.write(root / "server.py", SERVER)
    config = {"kind": "http", "boot": "python server.py", "ready": "auto", "timeout_s": 15,
              "routes": ["/"], "data": "none",
              "env": {"PORT": "$TALLER_SMOKE_PORT", "MODE": mode,
                      "HITS": str(tmp_path / "hits.log")}}
    config["env"].update(extra.pop("env", {}))
    config.update(extra)
    return root, {"smoke": config}


def found(verdict: dict, rule: str) -> list[dict]:
    return [f for f in verdict["findings"] if f["rule"] == rule]


def alive(pid: int) -> bool:
    if os.name == "nt":
        listing = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                 capture_output=True, text=True).stdout
        return str(pid) in listing
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


# --- http ----------------------------------------------------------------------------

def test_a_healthy_app_passes_on_an_allocated_port(tmp_path: Path):
    root, rules = app(tmp_path)

    verdict = smoke.run(root, rules)

    assert (verdict["gate"], verdict["result"], verdict["findings"]) == ("smoke", "pass", [])
    assert verdict["metrics"]["port"] not in (0, 5000)
    assert verdict["metrics"]["routes_checked"] == ["/"]


def test_boot_failure(tmp_path: Path):
    root, rules = app(tmp_path, "crash")

    verdict = smoke.run(root, rules)

    hits = found(verdict, "smoke.boot-failed")
    assert [h["severity"] for h in hits] == ["BLOCKER"]
    assert "the app could not start" in hits[0]["message"]


def test_a_500_is_a_route_error(tmp_path: Path):
    root, rules = app(tmp_path, routes=["/", "/broken"])

    verdict = smoke.run(root, rules)

    hits = found(verdict, "smoke.route-error")
    assert [(h["severity"], "/broken" in h["message"]) for h in hits] == [("BLOCKER", True)]


def test_a_302_to_login_is_not_rendered(tmp_path: Path):
    root, rules = app(tmp_path, routes=["/private"])

    hits = found(smoke.run(root, rules), "smoke.not-rendered")

    assert [h["severity"] for h in hits] == ["HIGH"] and "/login" in hits[0]["message"]


def test_an_empty_200_is_not_rendered(tmp_path: Path):
    root, rules = app(tmp_path, routes=["/empty"])

    hits = found(smoke.run(root, rules), "smoke.not-rendered")

    assert [h["severity"] for h in hits] == ["HIGH"] and "empty" in hits[0]["message"]


def test_basic_auth_sends_the_header_and_follows_redirects(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TALLER_SMOKE_SECRET", "s3cret")
    root, rules = app(tmp_path, routes=["/private"],
                      auth={"kind": "basic", "user": "smoke", "secret": "$TALLER_SMOKE_SECRET"})

    verdict = smoke.run(root, rules)

    assert verdict["result"] == "pass", verdict["findings"]


def test_timeout_reaps_the_process_tree(tmp_path: Path):
    pid_file = tmp_path / "child.pid"
    root, rules = app(tmp_path, "hang", timeout_s=3, env={"CHILD_PID": str(pid_file)})

    verdict = smoke.run(root, rules)

    assert [h["severity"] for h in found(verdict, "smoke.timeout")] == ["HIGH"]
    assert pid_file.exists() and not alive(int(pid_file.read_text()))


def test_two_runs_get_distinct_ports(tmp_path: Path):
    root, rules = app(tmp_path)
    verdicts: list[dict] = []
    threads = [threading.Thread(target=lambda: verdicts.append(smoke.run(root, rules)))
               for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert [v["result"] for v in verdicts] == ["pass", "pass"]
    assert len({v["metrics"]["port"] for v in verdicts}) == 2


def test_data_copy_never_touches_the_source_db_or_its_wal(tmp_path: Path):
    root, rules = app(tmp_path, "db", data="copy", database="instance/app.db",
                      env={"DATABASE": "$TALLER_SMOKE_DATA/app.db",
                           "DATA_DIR": "$TALLER_SMOKE_DATA"})
    live = {name: support.write(root / "instance" / name, f"live {name}")
            for name in ("app.db", "app.db-wal", "app.db-shm")}
    before = {name: (path.read_bytes(), path.stat().st_mtime_ns) for name, path in live.items()}

    verdict = smoke.run(root, rules)

    assert verdict["result"] == "pass", verdict["findings"]
    assert {n: (p.read_bytes(), p.stat().st_mtime_ns) for n, p in live.items()} == before


def test_mapped_routes_are_requested_and_an_unmapped_template_is_medium(tmp_path: Path):
    root, rules = app(tmp_path)

    verdict = smoke.run(root, rules, templates={"templates/ledger.html": ["/ledger"]},
                        changed=["templates/ledger.html", "templates/_row.html", "app.py"])

    hits = found(verdict, "smoke.unmapped-template")
    assert [(h["severity"], h["file"]) for h in hits] == [("MEDIUM", "templates/_row.html")]
    assert (tmp_path / "hits.log").read_text().split().count("/ledger") == 1
    assert verdict["metrics"]["routes_checked"] == ["/", "/ledger"]


# --- import and none -------------------------------------------------------------------

def test_import_kind_raising(tmp_path: Path):
    support.write(tmp_path / "main.py", "raise RuntimeError('no config file')\n")

    verdict = smoke.run(tmp_path, {"smoke": {"kind": "import", "module": "main",
                                             "timeout_s": 20}})

    hits = found(verdict, "smoke.boot-failed")
    assert [h["severity"] for h in hits] == ["BLOCKER"] and "no config file" in hits[0]["message"]


def test_import_kind_passing(tmp_path: Path):
    support.write(tmp_path / "main.py", "VALUE = 1\n")

    verdict = smoke.run(tmp_path, {"smoke": {"kind": "import", "module": "main"}})

    assert verdict["result"] == "pass"


def test_none_kind_passes_skipped(tmp_path: Path):
    verdict = smoke.run(tmp_path, {"smoke": {"kind": "none"}})

    assert verdict["result"] == "pass" and verdict["metrics"] == {"skipped": True}


def test_no_smoke_configuration_is_an_error_not_a_pass(tmp_path: Path):
    verdict = smoke.run(tmp_path, {})

    assert verdict["result"] == "error" and "smoke" in verdict["error"]


# --- criterion 3 -------------------------------------------------------------------------

def test_the_generated_flask_project_boots(tmp_home, identity):
    pytest.importorskip("flask")
    project = support.new_project()
    ruleset = constitution.resolve(project)

    verdict = smoke.run(project, ruleset)

    assert verdict["result"] == "pass", verdict
    assert not (project / "instance" / "app.db-wal").exists()
