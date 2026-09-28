"""The chief at ⑤ and ⑥: gates selected and run, verdicts written, findings routed.

Spec 7.1, 7.2, 9.2, 9.3, 9.7, 14. The gates here are the real ones - the real
constitution, size and tests over the real generated project, and smoke booting
it - so the only thing scripted is what a model would have written.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import support
from taller import chief, discovery, generated, gates, tickets
from taller.gates import smoke
from taller.gates import tests as tests_gate

CLASSIFY = {"value": {"kind": "bug", "title": "Warning red differs",
                      "summary": "The mismatch warning uses the app's danger colour."}}
EXPLORE = {"value": {"files": ["static/css/app.css"], "adds_or_deletes_files": False,
                     "schema_change": False, "route_change": False, "dependency_change": False,
                     "change_kind": "style", "notes": "One rule in app.css."}}
SUMMARY = {"value": {"summary_md": "The warning now uses the danger token."}}


def build(text: str, message: str = "fix(ui): the warning colour") -> dict:
    return {"value": {"summary": "Changed the warning colour.", "commits": []},
            "effects": [{"write": "static/css/app.css", "text": text}, {"commit": message}]}


TOKEN = build("h1 { color: var(--color-danger); }\n")
HEX = build("h1 { color: #dc3545; }\n")
FIX = {"value": {"summary": "Used the token.", "commits": []},
       "effects": [{"write": "static/css/app.css", "text": "h1 { color: var(--color-danger); }\n"},
                   {"commit": "fix(ui): use the danger token"}]}
NO_FIX = {"value": {"summary": "Could not find a token.", "commits": []}}
FIX_BY_TEST = {"value": {"summary": "Changed the test.", "commits": []},
               "effects": [{"write": "tests/test_app.py", "text": "def test_x():\n    pass\n"},
                           {"commit": "test: relax"}]}


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    return support.new_project()


@pytest.fixture
def script(tmp_path: Path, monkeypatch):
    path = tmp_path / "script.json"

    def install(**answers):
        path.write_text(json.dumps(answers), encoding="utf-8")
        monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(path))
    return install


@pytest.fixture
def prompts(tmp_path: Path, monkeypatch):
    """What each role was told, from the stub's stdin log."""
    log = tmp_path / "stdin.jsonl"
    monkeypatch.setenv("STUB_CLAUDE_STDIN", str(log))

    def of(role: str) -> list[str]:
        if not log.exists():
            return []
        entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        return [entry["stdin"] for entry in entries if entry["role"] == role]
    return of


def run(project: Path) -> dict:
    ticket_id = tickets.create(project, title="Placeholder", words="The warning red is wrong.",
                               kind="idea", named_by=None)["id"]
    return chief.run(project, ticket_id, say=lambda text: None)


def on_branch(project: Path, ticket: dict, name: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(project), "cat-file", "blob",
         f"{ticket['branch']}:{tickets.ticket_dir(ticket)}/{name}"],
        capture_output=True, text=True, encoding="utf-8")
    return completed.stdout if completed.returncode == 0 else None


def roles_called(stub_claude) -> list[str]:
    called = []
    for argv in stub_claude.calls():
        if "--append-system-prompt" in argv:
            brief = argv[argv.index("--append-system-prompt") + 1]
            called.append(brief.split(".", 1)[0].removeprefix("ROLE: "))
    return called


def verdict_of(gate: str, *found: dict, result: str | None = None) -> dict:
    out = gates.verdict(gate, list(found), {})
    if result:
        out["result"] = result
    return out


# --- the happy path ------------------------------------------------------------------

def test_a_clean_fast_change_passes_three_gates_and_smoke(project, script):
    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[TOKEN], summariser=[SUMMARY])

    ticket = run(project)

    assert (ticket["stage"], ticket["lane"], ticket["blocked"]) == ("review", "fast", None)
    assert ticket["gates"] == ["constitution", "size", "tests", "smoke"]
    assert {name: v["result"] for name, v in ticket["verdicts"].items()} == {
        "constitution": "pass", "size": "pass", "tests": "pass", "smoke": "pass"}
    assert ticket["fix_rounds"] == 0


def test_verdict_files_land_on_the_branch_and_counts_in_status(project, script):
    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[TOKEN], summariser=[SUMMARY])

    ticket = run(project)

    hub_sha = ticket["verdicts"]["constitution"]["hub_sha"]
    assert hub_sha and set(ticket["verdicts"]["size"]) == {
        "result", "blocker", "high", "medium", "low", "nit", "hub_sha"}
    for name in ticket["gates"]:
        parsed = gates.parse_verdict(on_branch(project, ticket, f"gates/{name}.md"))
        assert (parsed["gate"], parsed["hub_sha"]) == (name, hub_sha)
    assert gates.parse_verdict(on_branch(project, ticket, "gates/tests.md"))["metrics"][
        "tests_run"] > 0


# --- the fixer -----------------------------------------------------------------------

def test_a_hardcoded_colour_is_fixed_by_the_fixer_in_one_round(project, script, stub_claude):
    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[HEX], fixer=[FIX],
           summariser=[SUMMARY])

    ticket = run(project)

    assert (ticket["stage"], ticket["blocked"], ticket["fix_rounds"]) == ("review", None, 1)
    assert ticket["verdicts"]["constitution"]["result"] == "pass"
    fixer = [argv for argv in stub_claude.calls() if "ROLE: fixer" in " ".join(argv)]
    assert "tests/**" in " ".join(fixer[0])            # forbidden, by the harness
    notes = tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/notes.md").decode()
    assert "fix round 1" in notes


def test_the_fixer_is_told_the_findings(project, script, prompts):
    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[HEX], fixer=[FIX],
           summariser=[SUMMARY])

    run(project)

    told = prompts("fixer")[0]
    assert "brand.hardcoded-color" in told and "static/css/app.css:1" in told


def test_a_finding_that_survives_two_rounds_blocks(project, script, stub_claude):
    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[HEX], fixer=[NO_FIX, NO_FIX])

    ticket = run(project)

    assert ticket["stage"] == "gates" and ticket["fix_rounds"] == 2
    assert "survived 2 fix rounds" in ticket["blocked"]["reason"]
    assert "brand.hardcoded-color" in ticket["blocked"]["reason"]
    assert roles_called(stub_claude).count("fixer") == 2


def test_a_fixer_round_touching_a_test_is_reverted_and_escalated(project, script):
    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[HEX], fixer=[FIX_BY_TEST])

    ticket = run(project)

    assert "tests/test_app.py" in ticket["blocked"]["reason"]
    changed = subprocess.run(["git", "-C", str(project), "diff", "--name-only",
                              f"main...{ticket['branch']}"], capture_output=True,
                             text=True).stdout.split()
    assert "tests/test_app.py" not in changed, "the fixer's round was not undone"


# --- routing by remediation (§15.1) -----------------------------------------------------

@pytest.mark.parametrize("patch, rule", [
    ("tests", "tests.error"),
    ("smoke-boot", "smoke.boot-failed"),
    ("smoke-login", "smoke.not-rendered"),
])
def test_an_escalated_finding_blocks_without_a_fixer(project, script, stub_claude,
                                                     monkeypatch, patch, rule):
    if patch == "tests":
        monkeypatch.setattr(tests_gate, "run", lambda *a, **k: {
            "gate": "tests", "result": "error", "findings": [], "metrics": {},
            "error": "conftest.py could not be imported"})
    else:
        monkeypatch.setattr(smoke, "run", lambda *a, **k: verdict_of(
            "smoke", gates.finding(rule, "", 0, f"{rule} happened")))
    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[TOKEN])

    ticket = run(project)

    assert ticket["blocked"] and "fixer" not in roles_called(stub_claude)
    assert ticket["stage"] == ("smoke" if patch.startswith("smoke") else "gates")
    reason = ticket["blocked"]["reason"]
    assert rule in reason or "could not run" in reason


def test_a_file_too_long_goes_to_the_owner_without_a_fixer(project, script, stub_claude,
                                                           monkeypatch, prompts):
    """MEDIUM + escalate: §9.3 puts it in the owner's summary, §15.1 forbids a fixer."""
    from taller.gates import size

    monkeypatch.setattr(size, "run", lambda *a, **k: verdict_of(
        "size", gates.finding("size.file-too-long", "static/css/app.css", 0,
                              "app.css is 900 lines")))
    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[TOKEN], summariser=[SUMMARY])

    ticket = run(project)

    assert ticket["stage"] == "review" and "fixer" not in roles_called(stub_claude)
    assert "size.file-too-long (MEDIUM)" in prompts("summariser")[0]


def test_a_stale_snapshot_runs_taller_resolve_then_passes(project, script, monkeypatch):
    refreshed = []
    real_refresh = generated.refresh

    def refresh(path, *args, **kwargs):
        refreshed.append(tickets.load(path, 1)["stage"])
        return real_refresh(path, *args, **kwargs)

    # Main's snapshot reads as stale once - as if the hub moved between ② and ⑤ -
    # and the real value after `taller resolve` rewrote it.
    stale = {"sha": "0" * 40}
    real_sha = chief._main_snapshot_sha
    monkeypatch.setattr(generated, "refresh", refresh)
    monkeypatch.setattr(chief, "_main_snapshot_sha",
                        lambda path: stale.pop("sha", None) or real_sha(path))
    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[TOKEN], summariser=[SUMMARY])

    ticket = run(project)

    assert ticket["stage"] == "review" and not ticket["blocked"]
    assert "gates" in refreshed, "taller resolve did not run at ⑤"
    assert ticket["fix_rounds"] == 0


# --- ⑦ ---------------------------------------------------------------------------------

def test_medium_findings_reach_the_review_summary(project, script, prompts):
    sloppy = build("h1 { color: var(--color-danger); }\n", message="Fixed the colour")
    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[sloppy], summariser=[SUMMARY])

    ticket = run(project)

    assert ticket["stage"] == "review" and not ticket["blocked"]
    told = prompts("summariser")[0]
    assert "constitution.commit-message-shape (MEDIUM)" in told
    assert "- constitution: fail (1 medium)" in told


def test_rules_moving_mid_ticket_are_noted_at_review(project, script, prompts):
    from taller import hub

    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[TOKEN],
           summariser=[{"fail": "busy"}, {"fail": "busy"}, SUMMARY])
    ticket = run(project)
    assert ticket["stage"] == "review" and ticket["blocked"]

    config = hub.read_config()
    hub.update_config({"thresholds": {**config.get("thresholds", {}), "max_file_lines": 900}})
    hub.commit("raise the file limit")
    tickets.resume(project, ticket["id"])
    ticket = chief.run(project, ticket["id"], say=lambda text: None)

    assert ticket["stage"] == "review" and not ticket["blocked"]
    assert "rules changed since the gates ran" in prompts("summariser")[-1]
