"""gates/ core — the rule table, selection, routing, verdict files, and the Diff.

Spec 7.4, 9.2, 9.3, 9.7, 10.2.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import support
from taller import gates, overrides
from taller.gates import diff as diffs

RULESET = {"paths": {"ui": ["templates/**", "static/**/*.css"],
                     "security_sensitive": ["routes/**", ".env*"]}}


def change(*paths: str) -> dict:
    return {"base": "b", "head": "h", "commits": [],
            "files": [{"path": p, "status": "M", "added": [], "removed": [], "content": ""}
                      for p in paths]}


# --- the rule table (§9.7) -------------------------------------------------------

def test_rules_match_the_spec_table():
    assert gates.RULES["brand.hardcoded-color"] == ("HIGH", "agent")
    assert gates.RULES["constitution.new-ui-literal"] == ("MEDIUM", None)
    assert gates.RULES["constitution.resolved-snapshot-stale"] == ("HIGH", "command")
    assert gates.RULES["constitution.resolved-snapshot-modified"] == ("BLOCKER", "escalate")
    assert gates.RULES["size.file-too-long"] == ("MEDIUM", "escalate")
    assert gates.RULES["size.duplicate-block"] == ("LOW", None)
    assert gates.RULES["tests.failed"] == ("BLOCKER", "agent")
    assert gates.RULES["smoke.not-rendered"] == ("HIGH", "escalate")
    assert gates.RULES["tests.coverage-below-minimum"] == ("MEDIUM", "escalate")
    assert set(gates.RULES) == overrides.DECLARED_RULE_IDS


def test_a_finding_takes_its_severity_from_the_table():
    found = gates.finding("brand.hardcoded-color", "static/a.css", 3, "a literal #fff")

    assert (found["gate"], found["severity"], found["overridden"]) == ("constitution", "HIGH", None)


# --- selection (§9.2) ------------------------------------------------------------

@pytest.mark.parametrize("lane, paths, has_tests, expected", [
    ("fast", ["static/css/app.css"], False, ["constitution", "size"]),
    ("fast", ["app.py"], False, ["constitution", "size", "tests"]),
    ("fast", ["static/css/app.css"], True, ["constitution", "size", "tests"]),
    ("fast", ["templates/index.html"], False, ["constitution", "size"]),    # no ux on fast
    ("full", ["templates/index.html"], False, ["constitution", "size", "quality", "ux"]),
    ("full", ["routes/a.py"], True, ["constitution", "size", "tests", "security", "quality"]),
    ("full", ["config/.env.prod"], False, ["constitution", "size", "security", "quality"]),
])
def test_select(lane, paths, has_tests, expected):
    assert gates.select({"lane": lane}, change(*paths), RULESET, has_tests=has_tests) == expected


# --- routing (§9.3) --------------------------------------------------------------

def test_route_sends_each_finding_where_its_rule_says():
    found = [gates.finding("brand.hardcoded-color"), gates.finding("tests.error"),
             gates.finding("constitution.resolved-snapshot-stale"),
             gates.finding("constitution.new-ui-literal"), gates.finding("size.duplicate-block"),
             {**gates.finding("brand.hardcoded-font"), "severity": "LOW"}]

    routed = gates.route(found)

    assert [f["rule"] for f in routed["agent"]] == ["brand.hardcoded-color"]
    assert [f["rule"] for f in routed["escalate"]] == ["tests.error"]
    assert [f["rule"] for f in routed["command"]] == ["constitution.resolved-snapshot-stale"]
    assert [f["rule"] for f in routed["summary"]] == ["constitution.new-ui-literal"]
    assert {f["rule"] for f in routed["log"]} == {"size.duplicate-block", "brand.hardcoded-font"}


def test_an_overridden_blocker_is_only_logged():
    found = {**gates.finding("tests.failed"), "severity": "NIT",
             "overridden": {"reason": "flaky upstream", "source": "overrides.md"}}

    assert gates.route([found])["log"] == [found]


def test_an_llm_finding_carries_its_own_remediation():
    found = {"gate": "security", "severity": "HIGH", "rule": "security.csrf", "file": "a.py",
             "line": 1, "message": "no CSRF token", "fix_hint": None, "overridden": None,
             "remediation": "escalate"}

    assert gates.route([found])["escalate"] == [found]


def test_an_errored_verdict_escalates():
    verdict = {"gate": "tests", "result": "error", "findings": [], "metrics": {},
               "error": "pytest is not installed"}

    escalated = gates.errors([verdict])

    assert escalated[0]["severity"] == "BLOCKER" and "pytest is not installed" in escalated[0]["message"]
    assert gates.route(escalated)["escalate"] == escalated


# --- verdict files (§7.4) --------------------------------------------------------

def test_verdict_round_trips():
    verdict = {"gate": "constitution", "result": "fail", "metrics": {"files_checked": 2},
               "findings": [gates.finding("brand.hardcoded-color", "a.css", 1, "#fff")]}

    raw = gates.render_verdict(verdict, hub_sha="a3f9c21", prose="One literal colour.")
    parsed = gates.parse_verdict(raw.decode("utf-8"))

    assert b"\r" not in raw and raw.startswith(b"---\n")
    assert parsed["result"] == "fail" and parsed["hub_sha"] == "a3f9c21"
    assert parsed["counts"] == {"blocker": 0, "high": 1, "medium": 0, "low": 0, "nit": 0}
    assert parsed["findings"] == verdict["findings"]
    assert "One literal colour." in raw.decode("utf-8")


# --- the Diff (§10.2) ------------------------------------------------------------

def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


@pytest.fixture
def repo(tmp_path: Path, identity) -> Path:
    repo = support.make_repo(tmp_path / "repo", {"app.css": "a {}\nb {}\n", "keep.py": "x = 1\n"})
    git(repo, "checkout", "--quiet", "-b", "work")
    return repo


def commit(repo: Path, message: str) -> None:
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "-m", message)


def test_diff_lists_added_and_removed_lines_with_numbers(repo: Path):
    (repo / "app.css").write_text("a {}\nc { color: #fff; }\n", encoding="utf-8", newline="")
    (repo / "new.py").write_text("print(1)\n", encoding="utf-8", newline="")
    commit(repo, "fix(ui): colour")

    built = diffs.build(repo, "main", "work")

    by_path = {f["path"]: f for f in built["files"]}
    assert by_path["app.css"]["added"] == [{"line": 2, "text": "c { color: #fff; }"}]
    assert by_path["app.css"]["removed"] == [{"line": 2, "text": "b {}"}]
    assert by_path["new.py"]["status"] == "A" and by_path["new.py"]["content"] == "print(1)\n"
    assert [c["message"] for c in built["commits"]] == ["fix(ui): colour"]


def test_diff_survives_a_binary_and_a_latin1_file(repo: Path):
    (repo / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")
    (repo / "data.csv").write_bytes("caf\xe9\n".encode("latin-1"))
    commit(repo, "chore: assets")

    built = diffs.build(repo, "main", "work")

    by_path = {f["path"]: f for f in built["files"]}
    assert by_path["logo.png"]["content"] is None and by_path["logo.png"]["added"] == []
    assert by_path["data.csv"]["content"] is None


def test_diff_excludes_ticket_files(repo: Path):
    (repo / ".taller" / "work" / "0001-x").mkdir(parents=True)
    (repo / ".taller" / "work" / "0001-x" / "plan.md").write_text("plan\n", encoding="utf-8")
    commit(repo, "docs(plan): ticket 1")

    assert diffs.build(repo, "main", "work")["files"] == []


def test_tree_lists_every_tracked_file_as_added(repo: Path):
    built = diffs.tree(repo)

    by_path = {f["path"]: f for f in built["files"]}
    assert set(by_path) == {"app.css", "keep.py"}
    assert by_path["keep.py"]["added"] == [{"line": 1, "text": "x = 1"}]
