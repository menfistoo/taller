"""Phase G2's proof: what it uses, and what it may reach.

On an empty HOME with the stub `claude` and two projects: a piece of work is
carried by the chief, and What it uses names the model that did each job and
says where that work's usage went. Every request the stub saw carried
--strict-mcp-config while no service was allowed. Allowing a service on one
project gives it to that project's jobs only. A needs-you moment produces exactly
one notice through the chosen service, and never a second. No plain page names
the machine, and `taller doctor` finds nothing new wrong.
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import usage
from taller import (chief, cli, connections, constitution, config, discovery, doctor,
                    inference, notify, tickets)
from taller.prompter import ScriptedPrompter

FORBIDDEN = ("gate", "verdict", "lane", "checkpoint", "blocker", "severity", "branch",
             "commit", "sha", "sync", "worktree", "stage", "token", "mcp", "explorer",
             "architect")
LISTING = """claude.ai Google Drive: https://drive.example.test/mcp - ✔ Connected
claude.ai Todoist: https://tasks.example.test/mcp - ✔ Connected
"""
SCRIPT = {
    "chief": [{"value": {"kind": "bug", "title": "Heading uses the danger colour",
                         "summary": "The page heading should use the danger colour."}}],
    "explorer": [{"value": {"files": ["static/css/app.css"], "adds_or_deletes_files": False,
                            "schema_change": False, "route_change": False,
                            "dependency_change": False, "change_kind": "style",
                            "notes": "One rule in app.css.", "templates": {}}}],
    "implementer": [{"value": {"summary": "The heading uses the danger token.", "commits": []},
                     "effects": [{"write": "static/css/app.css",
                                  "text": "h1 { color: var(--color-danger, inherit); }\n"},
                                 {"commit": "fix(ui): the heading colour"}]}],
    "summariser": [{"value": {"summary_md": "The heading now uses the brand's own red."}}],
    "notifier": [{"value": {"added": True}}],
}



@pytest.fixture(autouse=True)
def work_use_ready(monkeypatch):
    """What is under the switch (connections.WORK_USE_READY), switched on."""
    monkeypatch.setattr(connections, "WORK_USE_READY", True)

@pytest.fixture
def two_projects(tmp_home: Path, identity, stub_claude, monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    monkeypatch.setattr(connections, "_run_list",
                        lambda: subprocess.CompletedProcess(["claude"], 0, LISTING, ""))
    monkeypatch.setattr(connections, "_learn_run", lambda prefix, server: [
        f"mcp__{prefix}__{name}" for name in {"google_drive": ["search_files", "share_file"],
                                              "todoist": ["add_tasks", "delete_object"]}[prefix]])
    connections.forget()
    toolshed, allotment = support.new_project("toolshed"), support.new_project("allotment")
    assert cli.main(["models", "probe"], ScriptedPrompter({})) == 0
    script = tmp_path / "script.json"
    script.write_text(json.dumps(SCRIPT), encoding="utf-8")
    monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(script))
    return toolshed, allotment


def requests(stub_claude) -> list[list[str]]:
    return [call for call in stub_claude.calls() if "-p" in call]


def text(client, where: str) -> str:
    raw = re.sub(r"(?s)<(style|script)\b.*?</\1>", " ", client.get(where).get_data(as_text=True))
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw)).split())


def machine_words(page: str) -> list[str]:
    return [w for w in FORBIDDEN if re.search(rf"\b{w}s?\b", page, re.IGNORECASE)]


def doctor_failures() -> list[str]:
    script = os.environ.pop("STUB_CLAUDE_SCRIPT", None)
    try:
        return [f"{c.name}: {c.detail}" for c in doctor.run_checks() if c.status == doctor.FAIL]
    finally:
        if script:
            os.environ["STUB_CLAUDE_SCRIPT"] = script


def test_what_it_uses_and_what_it_may_reach(two_projects, stub_claude):
    toolshed, allotment = two_projects
    client = cockpit.create_app(testing=True).test_client()
    at_start = doctor_failures()
    notify.choose("todoist", ["needs_you", "stopped"])
    connections.allow(allotment, "todoist", "look_and_add")     # Todoist is known here now
    connections.allow(allotment, "todoist", "off")

    # ① A piece of work, carried to her review; nothing of hers within its reach.
    made = tickets.create(toolshed, title="x", words="The heading is wrong.", kind="feature",
                          named_by=None)
    before = len(requests(stub_claude))
    chief.run(toolshed, int(made["id"]), say=lambda _: None)
    ticket = tickets.load(toolshed, 1)
    assert ticket["stage"] == "review" and ticket["blocked"] is None
    work = [call for call in requests(stub_claude)[before:]
            if "mcp__todoist__add_tasks" not in ",".join(call)]
    assert work and all("--strict-mcp-config" in call and "--mcp-config" not in call
                        for call in work), "no service while none is allowed"

    # ② What it uses names who did each job, and where this work's usage went.
    found = {job["name"]: job["model"] for job in usage.usage()["jobs"]}
    assert found["Reading your project"] == usage.model_name(ticket["spend"]["ran"]["explorer"])
    assert found["Understanding what you asked for"] == \
        usage.model_name(ticket["spend"]["ran"]["chief"])
    page = text(client, "/usage")
    assert "Heading uses the danger colour" in page and "toolshed · mostly" in page

    # ③ The moment it stopped for her was told once, through her Todoist - and only once.
    notices = [call for call in requests(stub_claude) if "mcp__todoist__add_tasks" in call]
    assert len(notices) == 1
    assert notices[0][notices[0].index("--allowedTools") + 1] == "mcp__todoist__add_tasks"
    assert notify.tell("toolshed", tickets.load(toolshed, 1), "needs_you")["sent"] is False
    assert len([c for c in requests(stub_claude) if "mcp__todoist__add_tasks" in c]) == 1

    # ④ A service allowed on one project reaches that project's jobs, and no other.
    connections.allow(toolshed, "google_drive", "look")

    def argv_for(project: Path) -> list[str]:
        dispatch = inference.Dispatch(role="explorer", prompt="hello",
                                      config=config.load_hub_config(),
                                      ruleset=constitution.resolve(project),
                                      tools=inference.role_tools("explorer"))
        return inference._build(dispatch, "claude")[0]

    given = argv_for(toolshed)
    assert json.loads(given[given.index("--mcp-config") + 1])["mcpServers"].keys() == \
        {"google_drive"}
    assert "mcp__google_drive__search_files" in given[given.index("--allowedTools") + 1]
    assert "mcp__google_drive__share_file" not in given[given.index("--allowedTools") + 1]
    assert "--mcp-config" not in argv_for(allotment)

    # Throughout: her words, and nothing new wrong.
    for where in ("/", "/usage", "/services", "/thing/toolshed/1"):
        assert machine_words(text(client, where)) == [], where
    assert [line for line in doctor_failures() if line not in at_start] == []
