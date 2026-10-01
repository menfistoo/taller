"""Phase G1's proof: asked for, worked on, decided and published - in plain words.

On an empty HOME with the stub `claude` and a project on (a stand-in for) GitHub:
she asks for something on `/ask`; the work starts by itself and the front page
shows it working; the chief carries it to her review; her page says what it did
and what its checks found, as sentences; she says yes and it is finished. Nothing
reaches GitHub until she presses Publish, and then it all does: the work, its pull
request and her ask. (Merging it and trying it out come after publishing, as
before.) Along the way she adds a rule of her own, changes an answer, reads a brand
guide into a brand, and makes one choice. No page she sees uses the machine's
words, and `taller doctor` finds nothing new wrong.
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import types
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import runs
from taller import brands, cli, discovery, doctor, issues, own_rules, settings, tickets
from taller.prompter import ScriptedPrompter

# The machine's words, which no plain page may use (as in test_plain_words).
FORBIDDEN = ("gate", "verdict", "lane", "checkpoint", "blocker", "severity",
             "branch", "commit", "sha", "sync", "worktree", "stage")
SCRIPT = {
    "chief": [{"value": {"kind": "bug", "title": "Heading uses the danger colour",
                         "summary": "The page heading should use the danger colour."}}],
    "explorer": [{"value": {"files": ["static/css/app.css"], "adds_or_deletes_files": False,
                            "schema_change": False, "route_change": False,
                            "dependency_change": False, "change_kind": "style",
                            "notes": "One rule in app.css.", "templates": {}}}],
    # A saved note titled the way nobody here titles them: a finding that is hers
    # to read, not one a fixer is sent after.
    "implementer": [{"value": {"summary": "The heading uses the danger token.",
                               "commits": []},
                     "effects": [{"write": "static/css/app.css",
                                  "text": "h1 { color: var(--color-danger, inherit); }\n"},
                                 {"commit": "Fixed the heading colour"}]}],
    "summariser": [{"value": {"summary_md": "The heading now uses the brand's own red.",
                              "files": {"static/css/app.css": "the page's colours"}}}],
}


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(bare)], check=True)
    return bare


@pytest.fixture
def github(monkeypatch) -> list[list[str]]:
    """Every `gh` call: what would have reached GitHub. Pushes go to the real remote."""
    calls: list[list[str]] = []

    def fake_gh(args, input=None, **kwargs):
        calls.append(list(args))
        if args[:2] == ["pr", "list"]:
            return subprocess.CompletedProcess(args, 0, "[]", "")
        if args[:2] == ["issue", "create"]:
            return subprocess.CompletedProcess(
                args, 0, "https://github.com/neighbourhood/toolshed/issues/5\n", "")
        if args[:2] == ["pr", "create"]:
            return subprocess.CompletedProcess(
                args, 0, "https://github.com/neighbourhood/toolshed/pull/7\n", "")
        return None

    monkeypatch.setattr(discovery, "_run_gh", fake_gh)
    monkeypatch.setattr(issues, "repo_of", lambda project: "neighbourhood/toolshed")
    return calls


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch, remote, github,
            tmp_path) -> Path:
    made = support.new_project(origin=str(remote))
    assert cli.main(["models", "probe"], ScriptedPrompter({})) == 0
    # After the probe: it dispatches too, and would eat the script's answers.
    script = tmp_path / "script.json"
    script.write_text(json.dumps(SCRIPT), encoding="utf-8")
    monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(script))
    return made


@pytest.fixture
def started(monkeypatch) -> list[list[str]]:
    """What the pages started, held until the test runs it - here, in-process."""
    seen: list[list[str]] = []

    def fake(command, log):
        seen.append(list(command))
        log.write_text("working\n", encoding="utf-8")
        return types.SimpleNamespace(pid=4321, poll=lambda: None)

    monkeypatch.setattr(runs, "_spawn", fake)
    return seen


def run_what_was_started(started: list[list[str]]) -> None:
    command = started.pop(0)
    assert command[1:3] == ["-m", "taller.cli"]
    prompter = ScriptedPrompter({})
    assert cli.main(command[3:], prompter) == 0, "\n".join(prompter.said)


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def seen(client, where: str, pages: dict[str, str], *, press: bool = False, **fields) -> str:
    """A page as she reads it - words only - kept for the vocabulary check. With
    `press` or any field, it is the page she lands on after sending a form."""
    if press or fields:
        answer = client.post(where, data={**token(client), **fields}, follow_redirects=True)
    else:
        answer = client.get(where)
    assert answer.status_code == 200, f"{where} -> {answer.status_code}"
    raw = re.sub(r"(?s)<(style|script)\b.*?</\1>", " ", answer.get_data(as_text=True))
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    pages[f"{where} ({len(pages)})"] = text
    return text


def machine_words(text: str) -> list[str]:
    return [word for word in FORBIDDEN if re.search(rf"\b{word}s?\b", text, re.IGNORECASE)]


def remote_heads(remote: Path) -> dict[str, str]:
    done = subprocess.run(["git", "--git-dir", str(remote), "for-each-ref",
                           "--format=%(refname:short) %(objectname)", "refs/heads"],
                          capture_output=True, text=True, check=True)
    return dict(line.split(" ", 1) for line in done.stdout.splitlines())


def created(github: list[list[str]]) -> list[str]:
    return [" ".join(call[:2]) for call in github if call[1:2] == ["create"]]


def doctor_failures() -> list[str]:
    """Every failing check. Doctor asks a model to say OK, so the script - which
    holds the answers for the work - is set aside while it does."""
    script = os.environ.pop("STUB_CLAUDE_SCRIPT", None)
    try:
        return [f"{c.name}: {c.detail}" for c in doctor.run_checks()
                if c.status == doctor.FAIL]
    finally:
        if script:
            os.environ["STUB_CLAUDE_SCRIPT"] = script


def test_asked_for_worked_on_decided_and_published(project, remote, github, started, tmp_path):
    client = cockpit.create_app(testing=True).test_client()
    pages: dict[str, str] = {}
    at_start = doctor_failures()

    # ① She asks, in her words; the work starts by itself.
    seen(client, "/ask", pages)
    seen(client, "/ask", pages, project="toolshed",
         # Short: the folder a piece of work is named after has to fit, with this
         # test's own deep temporary folder, under Windows' 260-character limit.
         words="Make the heading the danger red.")
    assert len(started) == 1 and started[0][-4:] == ["run", "1", "--path", str(project)]
    assert "Working" in seen(client, "/", pages)

    # ② The chief carries it to her; her page says what it did and what was found.
    run_what_was_started(started)
    ticket = tickets.load(project, 1)
    assert (ticket["stage"], ticket["blocked"]) == ("review", None), ticket["blocked"]
    page = seen(client, "/thing/toolshed/1", pages)
    assert "The heading now uses the brand's own red." in page
    assert "the page's colours" in page
    assert "One of its saved notes is not written the way your project writes them" in page
    assert "constitution.commit-message-shape" not in page

    # ③ Along the way: a rule of her own, one answer changed, and the rule survives.
    seen(client, "/project/toolshed/rules", pages)
    seen(client, "/project/toolshed/rules/add", pages, kind="always",
         text="Every page shows who has each tool.", why="That is the whole point.")
    seen(client, "/project/toolshed/about", pages)
    seen(client, "/project/toolshed/about", pages,
         what_it_does="Keeps track of which neighbour has which tool, and since when.")
    assert [rule["text"] for rule in own_rules.read(project)["always"]] == \
        ["Every page shows who has each tool."]
    assert "and since when" in seen(client, "/project/toolshed/about", pages)

    # ④ A brand guide, read into a proposal she checks and saves.
    guide = support.make_pdf(tmp_path / "guide.pdf", ["Primary #0F4C5C", "Accent #E36414"],
                             fonts=("Georgia",))
    with guide.open("rb") as handle:
        answer = client.post("/project/toolshed/look/guide", content_type="multipart/form-data",
                             data={**token(client), "guide": (handle, "guide.pdf")})
    assert "#0f4c5c" in html.unescape(answer.get_data(as_text=True)).lower()
    seen(client, "/project/toolshed/look/save", pages, new="1", name="Toolshed colours",
         **{"t:--color-primary": "#0f4c5c", "t:--color-accent": "#e36414"},
         prose="Calm and plain.")
    assert brands.list_brands() == ["toolshed-colours"]

    # ⑤ One choice: it tries once before asking her, in this project only.
    seen(client, "/project/toolshed/choices", pages)
    seen(client, "/project/toolshed/choices", pages, choice="tries", option="1")
    found = {key: (value, source) for key, value, source in settings.effective(project)}
    assert found["thresholds.max_fix_rounds"] == (1, "project")

    # ⑥ She says yes; it is finished - and nothing has left this computer.
    seen(client, "/thing/toolshed/1/yes", pages, press=True)
    run_what_was_started(started)
    ticket = tickets.load(project, 1)
    assert (ticket["stage"], ticket["blocked"], ticket["pr"]) == ("pr", None, None)
    finished = "finished, and waiting for you to publish it"
    assert finished in seen(client, "/", pages).lower()
    assert "it's finished here. publishing sends it" in         seen(client, "/thing/toolshed/1", pages).lower()
    assert remote_heads(remote) == {}, "something reached the remote before she said so"
    assert created(github) == [], "something reached GitHub before she said so"

    # ⑦ She presses Publish, and all of it goes: the work, its pull request, her ask.
    landed = seen(client, "/publish/toolshed", pages, press=True)
    assert "Published. Everything that was waiting has left this computer." in landed
    heads = remote_heads(remote)
    assert heads["main"] == support.git(project, "rev-parse", "main").strip()
    assert heads[ticket["branch"]] == support.git(project, "rev-parse", ticket["branch"]).strip()
    assert sorted(created(github)) == ["issue create", "pr create"]
    assert tickets.load(project, 1)["pr"] == 7
    assert "not left this computer" not in seen(client, "/", pages)

    # Throughout: her words, not the machine's; and nothing new is wrong.
    for where, text in pages.items():
        assert machine_words(text) == [], f"{where}: {machine_words(text)}"
    assert [line for line in doctor_failures() if line not in at_start] == []
