"""Phase C's proof: a gated ticket - flagged, fixed, booted, merged clean.

Criterion 3 - the generated application really boots under smoke and answers
`/`; criterion 14 - after the merge, `main` has no unsuppressed hardcoded brand
value. On an empty HOME, through the real commands, the real gates and the real
generated app; the stub `claude` stands in only for what a model would write.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from taller import cli, constitution, discovery, doctor, gates, paths, tickets
from taller.commands import brand as brand_command
from taller.commands import scan
from taller.prompter import ScriptedPrompter

NEW_PROJECT = {
    "setup.billing": "", "setup.host": "", "setup.language.code": "en",
    "setup.language.ui": "es", "setup.language.commits": "en",
    "q1": "Tracks which neighbour has borrowed which tool.", "q2": "A marketplace.",
    "q3": "Who has which tool.", "q4": "1", "q5": "", "q6": "", "q7": "Tools and loans.",
    "q8": "n", "q9": "1", "q10": "1", "q11": "", "q12": ["List the tools"], "brief": "1",
}
SCRIPT = {
    "chief": [{"value": {"kind": "bug", "title": "Heading uses the danger colour",
                         "summary": "The page heading should use the danger colour."}}],
    "explorer": [{"value": {"files": ["static/css/app.css"], "adds_or_deletes_files": False,
                            "schema_change": False, "route_change": False,
                            "dependency_change": False, "change_kind": "style",
                            "notes": "One rule in app.css.",
                            "templates": {}}}],
    # The implementer reaches for a literal - what the constitution gate is for.
    "implementer": [{"value": {"summary": "The heading is red now.", "commits": []},
                     "effects": [{"write": "static/css/app.css",
                                  "text": "h1 { color: #dc3545; }\n"},
                                 {"commit": "fix(ui): heading in the danger red"}]}],
    "fixer": [{"value": {"summary": "Replaced the literal with the danger token.",
                         "commits": []},
               "effects": [{"write": "static/css/app.css",
                            "text": "h1 { color: var(--color-danger, inherit); }\n"},
                           {"commit": "fix(ui): use the danger token"}]}],
    "summariser": [{"value": {"summary_md": "The heading uses the danger token."}}],
}


def run(argv: list[str], answers: dict | None = None) -> ScriptedPrompter:
    prompter = ScriptedPrompter(answers or {})
    code = cli.main(argv, prompter)
    assert code == 0, "\n".join(prompter.said)
    prompter.assert_all_used()
    return prompter


def test_a_gated_ticket_is_flagged_fixed_booted_and_merged_clean(
    tmp_home: Path, tmp_path: Path, stub_claude, identity, monkeypatch,
):
    monkeypatch.setattr(brand_command, "open_in_browser", lambda page: None)
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    projects = paths.home() / "projects"
    run(["project", "new", "toolshed", "--path", str(projects), "--no-open"], NEW_PROJECT)
    project = projects / "toolshed"
    at = ["--path", str(project)]
    run(["models", "probe"])

    script = tmp_path / "script.json"
    script.write_text(json.dumps(SCRIPT), encoding="utf-8")
    monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(script))

    run(["ticket", "new", "The", "heading", "should", "be", "the", "danger", "red", *at])
    run(["ticket", "run", "1", *at])
    ticket = tickets.load(project, 1)

    # ⑤ flagged the literal; one fixer round replaced it; the gates then passed.
    assert (ticket["stage"], ticket["blocked"], ticket["fix_rounds"]) == ("review", None, 1)
    notes = tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/notes.md").decode()
    assert "constitution fail" in notes and "fix round 1" in notes
    assert notes.index("fix round 1") < notes.rindex("constitution pass")
    fixer = [argv for argv in stub_claude.calls() if "ROLE: fixer" in " ".join(argv)]
    assert len(fixer) == 1 and "tests/**" in " ".join(fixer[0])

    # ⑥ booted the real generated application and GOT / (criterion 3).
    assert ticket["gates"] == ["constitution", "size", "tests", "smoke"]
    smoke = gates.parse_verdict(subprocess.run(
        ["git", "-C", str(project), "cat-file", "blob",
         f"{ticket['branch']}:{tickets.ticket_dir(ticket)}/gates/smoke.md"],
        capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    assert smoke["result"] == "pass" and smoke["metrics"]["routes_checked"] == ["/"]
    assert smoke["metrics"]["port"] != 5000

    # The owner approves, merges, releases.
    run(["ticket", "approve", "1", *at])
    run(["ticket", "run", "1", *at])
    subprocess.run(["git", "-C", str(project), "merge", "--quiet", "--no-edit",
                    ticket["branch"]], check=True, capture_output=True)
    run(["ticket", "run", "1", *at])
    run(["ticket", "approve", "1", *at])
    assert tickets.load(project, 1)["outcome"] == "done"

    # Criterion 14: main carries no unsuppressed hardcoded brand value.
    figures = scan.health(project, constitution.resolve(project))
    assert not [rule for rule, _ in figures["top_rules"] if rule.startswith("brand.hardcoded")]
    assert "var(--color-danger" in (project / "static" / "css" / "app.css").read_text("utf-8")

    # Doctor is green, with phase C's row passing.
    monkeypatch.delenv("STUB_CLAUDE_SCRIPT")
    assert cli.main(["doctor"], ScriptedPrompter({})) == 0
    row = [c for c in doctor.run_checks() if c.phase == "C"]
    assert [c.status for c in row] == [doctor.PASS]
