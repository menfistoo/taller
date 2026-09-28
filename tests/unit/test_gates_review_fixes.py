"""What the whole-branch review of phase C found, each pinned by a test.

The root cause of the three critical findings is one fact: a ticket worktree is
a fresh checkout, so it holds nothing the project gitignores - not the venv, not
the database. The gates must take those from the owner's checkout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import support
from taller import adopt, chief, config, inference, models, tickets
from taller.gates import llm, smoke
from taller.gates import tests as tests_gate

from test_chief_gates import (CLASSIFY, EXPLORE, FIX, HEX, SUMMARY, TOKEN,  # noqa: F401
                              build, on_branch, project, prompts, roles_called, run, script)
from test_gates_smoke import app

RULES = {"thresholds": {"min_coverage_pct": 0}, "paths": {"tests_dir": "tests"}}


def bare_venv(root: Path) -> Path:
    """A real venv with no pytest and no flask in it."""
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(root / ".venv")],
                   check=True, capture_output=True)
    return root


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


# --- C1, C2: the project's interpreter, and a missing pytest is an error -----------------

def test_the_tests_gate_uses_the_projects_venv_and_a_missing_pytest_is_an_error(tmp_path):
    owner = bare_venv(tmp_path / "owner")
    worktree = tmp_path / "worktree"
    support.write(worktree / "tests" / "test_a.py", "def test_one():\n    assert False\n")

    verdict = tests_gate.run(worktree, RULES, project=owner)

    assert verdict["result"] == "error" and verdict["findings"] == []
    assert "pytest" in verdict["error"] and ".venv" in verdict["error"]


def test_an_exit_1_naming_no_failed_test_is_an_error_not_a_failure(tmp_path):
    support.write(tmp_path / "conftest.py",
                  "def pytest_sessionfinish(session, exitstatus):\n"
                  "    session.exitstatus = 1\n")

    verdict = tests_gate.run(tmp_path, RULES)

    assert verdict["result"] == "error" and verdict["findings"] == []


def test_smoke_boots_python_under_the_projects_venv(tmp_path):
    owner = bare_venv(tmp_path / "owner")
    worktree, rules = app(tmp_path, env={"WHO": str(tmp_path / "who.txt")})
    support.write(worktree / "boot.py", "import os, sys\n"
                                        "open(os.environ['WHO'], 'w').write(sys.executable)\n"
                                        "exec(open('server.py').read())\n")
    rules["smoke"]["boot"] = "python boot.py"

    smoke.run(worktree, rules, project=owner)

    assert ".venv" in (tmp_path / "who.txt").read_text()


# --- C3: the database is copied from the owner's checkout --------------------------------

def test_data_copy_reads_the_database_from_the_project_not_the_worktree(tmp_path):
    owner = tmp_path / "owner"
    support.write(owner / "instance" / "app.db", "live rows")
    worktree, rules = app(tmp_path, "copied", data="copy", database="instance/app.db",
                          env={"DATABASE": "$TALLER_SMOKE_DATA/app.db", "EXPECT": "live rows"})

    verdict = smoke.run(worktree, rules, project=owner)

    assert verdict["result"] == "pass", verdict["findings"]
    assert (owner / "instance" / "app.db").read_text() == "live rows"


def test_a_project_that_never_ran_boots_on_an_empty_copy_and_says_so(tmp_path):
    worktree, rules = app(tmp_path, data="copy", database="instance/app.db",
                          env={"DATABASE": "$TALLER_SMOKE_DATA/app.db"})

    verdict = smoke.run(worktree, rules, project=tmp_path / "owner")

    assert verdict["result"] == "pass" and "no database" in verdict["metrics"]["data"]


# --- I7, I8: smoke configuration it cannot honour is refused ------------------------------

def test_an_http_smoke_that_ignores_the_allocated_port_is_refused(tmp_path):
    config_ = {"kind": "http", "boot": "python app.py", "ready": "auto", "routes": ["/"]}

    assert any("TALLER_SMOKE_PORT" in p for p in smoke.problems(config_))
    verdict = smoke.run(tmp_path, {"smoke": config_})
    assert verdict["result"] == "error" and "TALLER_SMOKE_PORT" in verdict["error"]


def test_form_auth_is_reported_as_unsupported(tmp_path):
    config_ = {"kind": "http", "boot": "python a.py $TALLER_SMOKE_PORT",
               "auth": {"kind": "form", "user": "u", "secret": "x"}}

    assert any("form" in p for p in smoke.problems(config_))


def test_a_secret_from_any_variable_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_SMOKE_PW", "s3cret")
    worktree, rules = app(tmp_path, routes=["/private"],
                          env={"EXPECT_AUTH": "smoke:s3cret"},
                          auth={"kind": "basic", "user": "smoke", "secret": "$MY_SMOKE_PW"})

    verdict = smoke.run(worktree, rules)

    assert verdict["result"] == "pass", verdict["findings"]
    assert smoke.problems(rules["smoke"]) == []


# --- I3: routes with parameters are not fetched literally ---------------------------------

def test_a_parameterised_route_counts_as_unmapped(tmp_path):
    worktree, rules = app(tmp_path)

    verdict = smoke.run(worktree, rules, templates={"templates/dia.html": ["/dia/<fecha>"]},
                        changed=["templates/dia.html"])

    assert [f["rule"] for f in verdict["findings"]] == ["smoke.unmapped-template"]
    assert "/dia/<fecha>" not in verdict["metrics"]["routes_checked"]


def test_the_explorer_is_asked_for_the_template_map():
    from taller import roles

    text = roles.definition("explorer")
    assert "templates" in text and "render_template" in text


# --- I6, M14: model findings are not silently lost; a gate model falls back --------------

@pytest.fixture
def stubbed(tmp_home, identity, stub_claude, tmp_path, monkeypatch):
    path = tmp_path / "script.json"

    def install(**answers):
        path.write_text(json.dumps(answers), encoding="utf-8")
        monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(path))
    return install


def test_a_rule_without_its_prefix_is_kept_and_a_bad_remediation_escalates(stubbed, tmp_path):
    stubbed(gate_security=[{"value": {"findings": [
        {"rule": "sql-injection", "severity": "BLOCKER", "file": "db.py", "line": 3,
         "message": "String-built SQL.", "fix_hint": None, "remediation": "fixer"},
        {"rule": "quality.dead-code", "severity": "HIGH", "file": "a.py", "line": 1,
         "message": "Unused.", "fix_hint": None, "remediation": "agent"}]}}])
    cfg = config.load_hub_config()

    verdict, _ = llm.run("security", tmp_path, {"id": 1, "title": "t"}, "", cfg, cfg)

    got = {(f["rule"], f["severity"], f["remediation"]) for f in verdict["findings"]}
    assert got == {("security.sql-injection", "BLOCKER", "escalate"),
                   ("security.quality.dead-code", "HIGH", "agent")}
    assert verdict["result"] == "fail"


def test_a_gate_whose_model_is_unavailable_falls_back(stubbed, tmp_path, monkeypatch):
    cfg = config.load_hub_config()
    monkeypatch.setenv("STUB_CLAUDE_FAIL_MODEL", config.resolve_model("gate_security", cfg))
    assert models.fallback_for("gate_security", cfg)
    stubbed(gate_security=[{"value": {"findings": []}}])

    verdict, result = llm.run("security", tmp_path, {"id": 1, "title": "t"}, "", cfg, cfg)

    assert verdict["result"] == "pass" and result.ok


# --- I5: the model gates see the whole change ---------------------------------------------

def test_gates_may_read_the_diff_themselves():
    for gate in ("gate_security", "gate_quality", "gate_ux"):
        assert "Bash(git diff*)" in inference.role_tools(gate)


def test_the_gate_patch_is_not_cut_at_the_roles_limit(project, script):
    big = "".join(f".rule-{n} {{ margin: {n}px; }}\n" for n in range(900))
    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[build(big)])

    ticket = run(project)                                  # promoted to full at ④

    patch = chief._gate_patch(project, ticket)
    assert len(patch) > chief.PATCH_SHOWN and "is cut" not in patch


# --- I1, I2, M4: what the fixer may and may not leave behind -------------------------------

def test_gate_artifacts_are_not_swept_into_the_fixers_commit(project, script, monkeypatch):
    real = tests_gate.run

    def noisy(worktree, ruleset, **kwargs):
        (Path(worktree) / "coverage.xml").write_text("<coverage/>", encoding="utf-8")
        return real(worktree, ruleset, **kwargs)
    monkeypatch.setattr(tests_gate, "run", noisy)
    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[HEX], fixer=[FIX],
           summariser=[SUMMARY])

    ticket = run(project)

    assert ticket["stage"] == "review" and not ticket["blocked"]
    changed = git(project, "diff", "--name-only", f"main...{ticket['branch']}").split()
    assert "coverage.xml" not in changed


@pytest.mark.parametrize("path", ["conftest.py", "pytest.ini", "tests/test_facturación.py"])
def test_the_fixer_may_not_switch_a_test_off_by_any_route(project, script, stub_claude, path):
    cheat = {"value": {"summary": "Quietened the suite.", "commits": []},
             "effects": [{"write": path, "text": "# changed\n"}, {"commit": "fix: quiet"}]}
    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[HEX], fixer=[cheat])

    ticket = run(project)

    assert ticket["blocked"] and path in ticket["blocked"]["reason"]
    changed = git(project, "-c", "core.quotepath=false", "diff", "--name-only",
                  f"main...{ticket['branch']}").split("\n")
    assert path not in changed
    fixer = [a for a in stub_claude.calls() if "ROLE: fixer" in " ".join(a)][0]
    assert "conftest.py" in " ".join(fixer) and "pytest.ini" in " ".join(fixer)


# --- I4: MEDIUM findings reach the owner verbatim ------------------------------------------

def test_medium_findings_are_written_into_review_md_verbatim(project, script):
    sloppy = build("h1 { color: var(--color-danger); }\n", message="Fixed the colour")
    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[sloppy], summariser=[SUMMARY])

    ticket = run(project)

    review = on_branch(project, ticket, "review.md")
    assert "The warning now uses the danger token." in review
    assert "constitution.commit-message-shape (MEDIUM)" in review


# --- I9: a failure already on main is not the change's to fix -------------------------------

def test_a_test_already_failing_on_main_does_not_spend_fixer_rounds(project, script,
                                                                    stub_claude, prompts):
    support.write(project / "tests" / "test_known.py", "def test_known_bad():\n"
                                                       "    assert 1 == 2\n")
    git(project, "add", "--all")
    git(project, "commit", "-q", "-m", "test: a known failure")
    script(chief=[CLASSIFY], explorer=[EXPLORE], implementer=[TOKEN], summariser=[SUMMARY])

    ticket = run(project)

    assert ticket["stage"] == "review" and not ticket["blocked"]
    assert "fixer" not in roles_called(stub_claude)
    assert "already failing on main" in prompts("summariser")[0]


# --- I10: scan runs the owner's suite away from her checkout --------------------------------

def test_scan_runs_the_suite_outside_the_owners_checkout(project):
    from taller import constitution
    from taller.commands import scan

    support.write(project / "tests" / "test_writes.py",
                  "from pathlib import Path\n\n"
                  "def test_write():\n    Path('artifact.txt').write_text('x')\n")
    git(project, "add", "--all")
    git(project, "commit", "-q", "-m", "test: writes a file")
    worktrees = git(project, "worktree", "list")

    figures = scan.health(project, constitution.resolve(project))

    assert figures["tests"]["tests_run"] > 0
    assert not (project / "artifact.txt").exists()
    assert git(project, "worktree", "list") == worktrees


# --- M13: adoption never half-applies over a review directory git does not track ----------

def test_an_untracked_review_directory_is_not_proposed_for_removal(tmp_home, identity):
    repo = support.make_repo(tmp_home / "p", {"app.py": "x = 1\n",
                                              ".gitignore": "code-review/\n"})
    support.write(repo / "code-review" / "notes.md", "local only\n")

    assert adopt.derive(repo)["review_dirs"] == []
