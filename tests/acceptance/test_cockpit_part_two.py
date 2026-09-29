"""Phase E part two's proof: a project made, settled and measured from the browser.

On an empty HOME with the stub `claude`: the twelve questions answered through
the cockpit's own form, a real project created from them, its settings changed,
one of its rules amended, its health checked, and a real ticket's spend shown -
every one of those through the test client and nothing else. The library does
the writing throughout, so the project it leaves behind is one the terminal
would have left.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import health, interview, rules
from taller import cli, constitution, discovery, hub, onboarding, paths, registry, tickets
from taller.commands import brand as brand_command
from taller.prompter import ScriptedPrompter

ANSWERS = {
    "what_it_does": "Keeps track of which neighbour has borrowed which tool.",
    "what_it_is_not": "It will never take payments.",
    "must_never_break": "Knowing who has which tool right now.",
    "users": "solo", "reach": "this machine", "phone": "n",
    "stores": "The tools, the neighbours, and who borrowed what.",
    "sensitive_data": "n", "profile": "flask-sqlite", "brand": "none", "deploy": "local",
    "first_version": "A page listing my tools\nA form to record a loan",
}
SCRIPT = {
    "chief": [{"value": {"kind": "bug", "title": "Heading uses the danger colour",
                         "summary": "The page heading should use the danger colour."}}],
    "explorer": [{"value": {"files": ["static/css/app.css"], "adds_or_deletes_files": False,
                            "schema_change": False, "route_change": False,
                            "dependency_change": False, "change_kind": "style",
                            "notes": "One rule in app.css.", "templates": {}}}],
    "implementer": [{"value": {"summary": "The heading uses the danger token.",
                               "commits": []},
                     "effects": [{"write": "static/css/app.css",
                                  "text": "h1 { color: var(--color-danger, inherit); }\n"},
                                 {"commit": "fix(ui): the heading colour"}]}],
    "summariser": [{"value": {"summary_md": "The heading uses the danger token."}}],
}


@pytest.fixture
def hub_ready(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    """A hub that has been through `taller setup`, and no project at all."""
    monkeypatch.setattr(brand_command, "open_in_browser", lambda page: None)
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    if not (hub.read_config().get("language") or {}).get("code"):
        hub.update_config({"language": {"code": "en", "ui": "es", "commits": "en"}})
    from taller import catalogue
    catalogue.install_profile("flask-sqlite")
    hub.commit("setup")
    return tmp_home / "projects"


@pytest.fixture
def client(hub_ready):
    return cockpit.create_app(testing=True).test_client()


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def post(client, where: str, **fields) -> str:
    answer = client.post(where, data={**token(client), **fields}, follow_redirects=True)
    assert answer.status_code == 200, f"{where} -> {answer.status_code}"
    return answer.get_data(as_text=True)


def test_a_project_is_made_settled_and_measured_from_the_browser(hub_ready, client,
                                                                 monkeypatch, tmp_path):
    projects = hub_ready

    # ① The twelve questions, in the browser, validated by the library.
    post(client, "/new", name="toolshed", path=str(projects))
    for question in onboarding.QUESTIONS:
        raw = ANSWERS[question.key]
        if question.key == "profile":
            raw = interview.page("toolshed")["choices"][0][0]
        post(client, "/new/toolshed", key=question.key, value=raw)
    brief = client.get("/new/toolshed").get_data(as_text=True)
    assert "Keeps track of which neighbour" in brief
    assert not (projects / "toolshed").exists(), "the brief created something"

    post(client, "/new/toolshed/create")
    project = projects / "toolshed"
    assert (project / ".taller" / "taller.yml").is_file()
    assert "toolshed" in [entry["name"] for entry in registry.list_projects()]
    assert onboarding.load_progress("toolshed") == {}

    # ② Settings: the layer a value came from, and the layer a change goes to.
    before = client.get("/settings?project=toolshed").get_data(as_text=True)
    assert "thresholds.max_file_lines" in before and "default" in before
    post(client, "/settings", project="toolshed", key="thresholds.max_file_lines",
         value="500")
    snapshot = json.loads((project / ".taller" / "resolved.json").read_text("utf-8"))
    assert snapshot["thresholds"]["max_file_lines"] == 500

    # ③ A rule amended in the browser reaches the snapshot the gates read.
    conventions = str(paths.project_constitution(project) / "conventions.md")
    post(client, "/rules/toolshed", path=conventions, reason="Bare excepts hide the cause",
         text="# Conventions\n\nNever use a bare except.\n")
    snapshot = json.loads((project / ".taller" / "resolved.json").read_text("utf-8"))
    assert "Never use a bare except." in json.dumps(snapshot)
    assert "amend: Bare excepts hide the cause" in support.git(
        project, "log", "--format=%s", "-5")

    # ④ Health: nothing is scanned until she asks, and then it is.
    assert health.last("toolshed") is None
    post(client, "/health/toolshed")
    checked = health.last("toolshed")
    assert checked["gates"] == ["constitution", "size", "tests"]
    assert "tests_run" in checked["tests"] or checked["errors"]

    # ⑤ A real ticket, carried by the chief, then read and decided in the browser.
    assert cli.main(["models", "probe"], ScriptedPrompter({})) == 0
    # After the probe: it dispatches too, and would eat the script's answers.
    script = tmp_path / "script.json"
    script.write_text(json.dumps(SCRIPT), encoding="utf-8")
    monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(script))
    at = ["--path", str(project)]
    assert cli.main(["ticket", "new", "The", "heading", "is", "wrong", *at],
                    ScriptedPrompter({})) == 0

    # The ask can still be changed, because no work has started.
    post(client, "/ticket/toolshed/1/change", title="The heading colour",
         words="The red is wrong; use the brand's own.")
    assert tickets._words(project, tickets.load(project, 1)).strip() == \
        "The red is wrong; use the brand's own."

    assert cli.main(["ticket", "run", "1", *at], ScriptedPrompter({})) == 0
    ticket = tickets.load(project, 1)
    assert (ticket["stage"], ticket["blocked"]) == ("review", None)

    # ⑥ Spend: the weighted figure, and no money at all on a subscription.
    page = client.get("/spend").get_data(as_text=True)
    assert "The heading colour" in page
    assert "$" not in page and "USD" not in page.upper()
    assert int(ticket["spend"]["weighted_tokens"]) >= 0

    # Once the work has started, the ask is no longer hers to edit quietly.
    assert "Change what you asked for" not in \
        client.get("/ticket/toolshed/1").get_data(as_text=True)

    # ⑦ The browser wrote nothing the library would not have written.
    assert support.git(project, "status", "--porcelain").strip() == ""
    monkeypatch.delenv("STUB_CLAUDE_SCRIPT")
    assert cli.main(["doctor"], ScriptedPrompter({})) == 0
