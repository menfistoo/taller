"""The plugin's proof: Taller driven the way a chat drives it.

Each step runs `taller` exactly as a command file tells a chat to - with an
answers file, no terminal, and the NEEDS loop: run, and while Taller exits 3
with `NEEDS <id>`, "ask the owner" (here: look the answer up), add it to the
file, and run the same command again. On an empty HOME, with the stub `claude`
standing in for every model. Plugin plan, Task 6.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from taller import cli, discovery, doctor, paths, tickets
from taller.commands import brand as brand_command
from taller.commands import hook

# What the owner would say, by the id Taller asks it under.
OWNER = {
    "setup.billing": "", "setup.host": "", "setup.language.code": "en",
    "setup.language.ui": "es", "setup.language.commits": "en", "setup.review": "1",
    "q1": "Tracks which neighbour has borrowed which tool.", "q2": "A marketplace.",
    "q3": "Who has which tool.", "q4": "1", "q5": "", "q6": "", "q7": "Tools and loans.",
    "q8": "n", "q9": "1", "q10": "1", "q11": "", "q12": ["List the tools"], "brief": "1",
    "resume": "y",
}
CLASSIFY = {"value": {"kind": "bug", "title": "Heading uses the danger colour",
                      "summary": "The page heading should use the danger colour."}}
EXPLORE = {"value": {"files": ["static/css/app.css"], "adds_or_deletes_files": False,
                     "schema_change": False, "route_change": False, "dependency_change": False,
                     "change_kind": "style", "notes": "One rule in app.css."}}
BUILD = {"value": {"summary": "The heading uses the danger token.", "commits": []},
         "effects": [{"write": "static/css/app.css",
                      "text": "h1 { color: var(--color-danger, inherit); }\n"},
                     {"commit": "fix(ui): heading uses the danger token"}]}
SUMMARY = {"value": {"summary_md": "One rule in static/css/app.css changed."}}
ROUNDS = 40


def chat_runs(argv: list[str], answers: Path, capsys) -> str:
    """One command, through the NEEDS loop, as a command file instructs."""
    for _ in range(ROUNDS):
        code = cli.main(["--answers", str(answers), *argv])
        out = capsys.readouterr().out
        if code != cli.EXIT_NEEDS_ANSWER:
            assert code == 0, out
            return out
        qid = re.search(r"^NEEDS (\S+)$", out, re.MULTILINE).group(1)
        assert qid in OWNER, f"Taller asked {qid}, which the owner was never asked about:\n{out}"
        sheet = json.loads(answers.read_text(encoding="utf-8")) if answers.exists() else {}
        sheet[qid] = OWNER[qid]
        answers.write_text(json.dumps(sheet), encoding="utf-8")
    raise AssertionError(f"`taller {' '.join(argv)}` still needed answers after {ROUNDS} rounds")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def test_taller_driven_the_way_a_chat_drives_it(tmp_home: Path, tmp_path: Path, stub_claude,
                                                identity, monkeypatch, capsys):
    monkeypatch.setattr(brand_command, "open_in_browser", lambda page: None)
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)          # no keyboard in a chat
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"chief": [CLASSIFY, CLASSIFY], "explorer": [EXPLORE, EXPLORE],
                                  "implementer": [BUILD, BUILD],
                                  "summariser": [SUMMARY, SUMMARY]}), encoding="utf-8")
    monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(script))
    projects = paths.home() / "projects"
    projects.mkdir(parents=True)
    monkeypatch.setitem(OWNER, "setup.roots", str(projects))    # "my projects live here"

    # /taller:onboard new toolshed - every question answered one NEEDS at a time.
    chat_runs(["setup"], tmp_path / "onboard.json", capsys)
    chat_runs(["project", "new", "toolshed", "--path", str(projects), "--no-open"],
              tmp_path / "onboard.json", capsys)
    project = projects / "toolshed"
    at = ["--path", str(project)]

    # /taller:new, then the background run.
    chat_runs(["ticket", "new", "The", "heading", "should", "be", "the", "danger", "red", *at],
              tmp_path / "new.json", capsys)
    chat_runs(["ticket", "run", "1", *at], tmp_path / "new.json", capsys)
    assert tickets.load(project, 1)["stage"] == "review"

    # /taller:status
    listed = chat_runs(["ticket", "list", *at], tmp_path / "status.json", capsys)
    assert "0001" in listed

    # /taller:reject 1 with the owner's reason.
    chat_runs(["ticket", "reject", "1", "--reason", "Use the brand's own red", *at],
              tmp_path / "reject.json", capsys)
    assert tickets.load(project, 1)["stage"] == "triage"

    # A second ticket carried all the way: new, approve, merge, release.
    chat_runs(["ticket", "new", "Make", "the", "heading", "red", *at], tmp_path / "new.json",
              capsys)
    chat_runs(["ticket", "run", "2", *at], tmp_path / "new.json", capsys)
    chat_runs(["ticket", "approve", "2", *at], tmp_path / "approve.json", capsys)
    chat_runs(["ticket", "run", "2", *at], tmp_path / "approve.json", capsys)
    git(project, "merge", "--quiet", "--no-edit", tickets.load(project, 2)["branch"])
    chat_runs(["ticket", "run", "2", *at], tmp_path / "approve.json", capsys)
    chat_runs(["ticket", "approve", "2", *at], tmp_path / "approve.json", capsys)
    assert tickets.load(project, 2)["outcome"] == "done"

    # /taller:amend after the chat edited a shared rule.
    module = paths.hub() / "modules" / "never.md"
    module.write_text(module.read_text(encoding="utf-8") + "\n- No inline styles.\n",
                      encoding="utf-8", newline="")
    said = chat_runs(["amend", "--reason", "No inline styles"], tmp_path / "amend.json", capsys)
    assert "toolshed" in said

    # A chat opening in the project is briefed: its name, and the ticket still open.
    briefing = hook.briefing(project)
    assert "toolshed" in briefing and "0001" in briefing and "0002" not in briefing

    monkeypatch.delenv("STUB_CLAUDE_SCRIPT")               # doctor's own trivial dispatch
    assert cli.main(["doctor"]) == 0, capsys.readouterr().out
