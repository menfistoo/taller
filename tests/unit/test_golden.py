"""Spec 15.2 and 15.3: the fixture of deliberate violations, and the golden tickets.

15.2: every violation in `tests/fixtures/broken-app` is caught by its gate, by
rule id AND at the severity §9.7 declares - detection alone is not enough,
because severity decides whether a fix round is spent.

15.3: twelve synthetic requests - explorer facts and the diff that resulted -
with the lane, the promotion and the gate selection each must produce. No real
request has been recorded yet; these pin the same decisions (plan: deferred).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

import support
from taller import chief, config, gates, overrides
from taller.gates import constitution as constitution_gate
from taller.gates import diff as gate_diff
from taller.gates import llm, size, smoke
from taller.gates import tests as tests_gate

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "broken-app"
PROFILE = ROOT / "src" / "taller" / "catalogue" / "profiles" / "flask-sqlite.yml"
OVERRIDES = ".taller/constitution/overrides.md"


def flask_ruleset(**extra: Any) -> dict[str, Any]:
    """What `constitution.resolve` gives a flask-sqlite project, without a hub."""
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    merged = config.deep_merge(config.SHIPPED_DEFAULTS,
                               {k: v for k, v in profile.items()
                                if k not in ("name", "description", "modules", "brand")})
    merged.update({"hub_sha": "a" * 40, "language": {"code": "en", "ui": "es"},
                   "overrides": [], "slices": {}, **extra})
    return merged


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


# --- §15.2 ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def broken(tmp_path_factory) -> dict[str, Any]:
    """The fixture on a branch, every model-free gate run once over it."""
    repo = tmp_path_factory.mktemp("golden") / "broken-app"
    shutil.copytree(FIXTURE, repo)
    identity = ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    keep = {"README.md", ".taller"}
    parked = repo.parent / "parked"
    parked.mkdir()
    for entry in list(repo.iterdir()):
        if entry.name not in keep | {".git"}:
            shutil.move(str(entry), str(parked / entry.name))
    subprocess.run(["git", *identity, "-C", str(repo), "add", "--all"], check=True)
    subprocess.run(["git", *identity, "-C", str(repo), "commit", "-q", "-m", "chore: base"],
                   check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "ticket"], check=True)
    for entry in list(parked.iterdir()):
        shutil.move(str(entry), str(repo / entry.name))
    subprocess.run(["git", *identity, "-C", str(repo), "add", "--all"], check=True)
    subprocess.run(["git", *identity, "-C", str(repo), "commit", "-q", "-m", "Fixed stuff"],
                   check=True)

    rules = flask_ruleset(
        non_suppressible=["brand.hardcoded-font"],
        overrides=overrides.parse((FIXTURE / OVERRIDES).read_text(encoding="utf-8"),
                                  source=OVERRIDES))
    rules["smoke"] = {**rules["smoke"], "routes": ["/", "/broken"]}
    snapshot = json.loads((FIXTURE / ".taller" / "resolved.json").read_text())["hub_sha"]
    change = gate_diff.build(repo, "main", "ticket")
    verdicts = {
        "constitution": constitution_gate.run(change, rules, snapshot_sha=snapshot),
        "size": size.run(change, rules, tree=gate_diff.tree(repo)),
        "tests": tests_gate.run(repo, rules),
        "smoke": smoke.run(repo, rules),
    }
    return {"repo": repo, "rules": rules, "change": change, "verdicts": verdicts}


@pytest.mark.parametrize("gate, rule, severity, count", [
    ("constitution", "brand.hardcoded-color", "HIGH", 3),        # 3 hex where a token exists
    ("size", "size.function-too-long", "MEDIUM", 1),
    ("size", "size.duplicate-block", "LOW", 1),
    ("constitution", "constitution.new-ui-literal", "MEDIUM", 2),  # the English UI string
    ("constitution", "constitution.root-markdown", "MEDIUM", 1),
    ("constitution", "constitution.single-use-script", "MEDIUM", 1),
    ("constitution", "constitution.override-without-reason", "HIGH", 1),
    ("constitution", "constitution.override-expired", "HIGH", 1),
    ("constitution", "constitution.override-not-permitted", "BLOCKER", 2),  # security, n-s
    ("constitution", "constitution.layer-violation", "HIGH", 1),
    ("smoke", "smoke.route-error", "BLOCKER", 1),               # the template that raises
    ("constitution", "constitution.resolved-snapshot-stale", "HIGH", 1),
])
def test_every_mechanical_violation_by_rule_and_severity(broken, gate, rule, severity, count):
    hits = [f for f in broken["verdicts"][gate]["findings"] if f["rule"] == rule]

    assert len(hits) == count, [h["message"] for h in hits]
    assert {h["severity"] for h in hits} == {severity}
    assert gates.RULES[rule][0] == severity                       # the §9.7 table itself


def test_the_raising_template_fails_smoke_not_pytest(broken):
    assert broken["verdicts"]["tests"]["result"] == "pass"
    route_error = [f for f in broken["verdicts"]["smoke"]["findings"]
                   if f["rule"] == "smoke.route-error"]
    assert "/broken" in route_error[0]["message"]


def test_the_refused_overrides_name_the_rules_they_target(broken):
    refused = [f["message"] for f in broken["verdicts"]["constitution"]["findings"]
               if f["rule"] == "constitution.override-not-permitted"]
    assert any("security.missing-permission" in m for m in refused)
    assert any("brand.hardcoded-font" in m for m in refused)


def test_a_project_cannot_remove_a_hub_non_suppressible_entry():
    hub = {"non_suppressible": ["brand.hardcoded-color"]}

    merged = config.deep_merge(hub, {"non_suppressible": []})

    assert "brand.hardcoded-color" in merged["non_suppressible"]
    assert not overrides.is_suppressible("brand.hardcoded-color", merged)


LLM_ROWS = [
    ("security", {"rule": "security.missing-permission", "severity": "HIGH",
                  "file": "routes/__init__.py", "line": 17,
                  "message": "/ledger has no permission check.",
                  "fix_hint": "Add @permission_required.", "remediation": "agent"}),
    ("ux", {"rule": "ux.ui-language", "severity": "MEDIUM", "file": "templates/index.html",
            "line": 5, "message": "\"Save changes\" is English; the UI language is es.",
            "fix_hint": "Translate it.", "remediation": "agent"}),
]


@pytest.mark.parametrize("gate, answer", LLM_ROWS, ids=[row[0] for row in LLM_ROWS])
def test_the_model_gate_rows(gate, answer, tmp_home, identity, stub_claude, tmp_path,
                             monkeypatch):
    script = tmp_path / "script.json"
    script.write_text(json.dumps({f"gate_{gate}": [{"value": {"findings": [answer]}}]}),
                      encoding="utf-8")
    monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(script))
    rules = flask_ruleset()

    verdict, _ = llm.run(gate, tmp_path, {"id": 1, "title": "broken-app"}, "", rules,
                         config.load_hub_config())

    assert [(f["rule"], f["severity"]) for f in verdict["findings"]] == [
        (answer["rule"], answer["severity"])]
    if gate == "security":
        applied = overrides.apply(verdict["findings"], {**rules, "overrides": [
            {"rule": answer["rule"], "scope": "*", "reason": "internal", "until": None,
             "source": OVERRIDES}]})
        assert applied[0]["severity"] == "HIGH"                     # never suppressed


# --- §15.3 golden tickets ---------------------------------------------------------------

def facts(*files: str, kind: str = "style", **flags: bool) -> dict[str, Any]:
    base = {"files": list(files), "adds_or_deletes_files": False, "schema_change": False,
            "route_change": False, "dependency_change": False, "change_kind": kind,
            "notes": ""}
    return {**base, **flags}


def diff(*files: tuple[str, str, int]) -> dict[str, Any]:
    return {"files": [{"path": p, "status": s, "lines": n} for p, s, n in files],
            "tracked": ["tests/test_app.py", "app.py"]}


GOLDEN = [
    # (name, explorer facts, resulting diff, lane, promotion (substring or None), gates)
    ("a colour in one stylesheet", facts("static/css/app.css"),
     diff(("static/css/app.css", "M", 2)), "fast", None,
     ["constitution", "size", "tests"]),
    ("a label in one template - ux NOT selected on fast",
     facts("templates/index.html", kind="string"),
     diff(("templates/index.html", "M", 2)), "fast", None,
     ["constitution", "size", "tests"]),
    ("promoted on size", facts("static/css/app.css"),
     diff(("static/css/app.css", "M", 80)), "fast", "lines changed",
     ["constitution", "size", "tests", "quality", "ux"]),
    ("promoted on a newly touched security path", facts("static/css/app.css"),
     diff(("routes/__init__.py", "M", 3)), "fast", "routes/**",
     ["constitution", "size", "tests", "security", "quality"]),
    ("promoted on a second file", facts("static/css/app.css"),
     diff(("static/css/app.css", "M", 2), ("templates/index.html", "M", 2)), "fast",
     "2 files changed", ["constitution", "size", "tests", "quality", "ux"]),
    ("a threshold in app.py", facts("app.py", kind="threshold"),
     diff(("app.py", "M", 1)), "fast", None, ["constitution", "size", "tests"]),
    ("a new page", facts("templates/ledger.html", "routes/__init__.py", kind="other",
                         adds_or_deletes_files=True, route_change=True),
     diff(("templates/ledger.html", "A", 30), ("routes/__init__.py", "M", 8)), "full", None,
     ["constitution", "size", "tests", "security", "quality", "ux"]),
    ("a schema change", facts("database.py", kind="other", schema_change=True),
     diff(("database.py", "M", 12)), "full", None,
     ["constitution", "size", "tests", "security", "quality"]),
    ("a dependency bump", facts("requirements.txt", kind="other", dependency_change=True),
     diff(("requirements.txt", "M", 1)), "full", None,
     ["constitution", "size", "tests", "quality"]),
    ("the compose file", facts("docker-compose.yml", kind="literal"),
     diff(("docker-compose.yml", "M", 1)), "full", None,
     ["constitution", "size", "tests", "security", "quality"]),
    ("a secret-looking path", facts("config/app_secret.py", kind="literal"),
     diff(("config/app_secret.py", "M", 1)), "full", None,
     ["constitution", "size", "tests", "security", "quality"]),
    ("a refactor across helpers", facts("utils/money.py", "utils/dates.py", kind="other"),
     diff(("utils/money.py", "M", 40), ("utils/dates.py", "M", 30)), "full", None,
     ["constitution", "size", "tests", "quality"]),
]


@pytest.mark.parametrize("name, found, change, lane, promotion, selected", GOLDEN,
                         ids=[case[0] for case in GOLDEN])
def test_golden_ticket(name, found, change, lane, promotion, selected):
    rules = flask_ruleset()

    decided, reason = chief.decide_lane(found, rules)
    promoted = chief.needs_promotion(change, {"lane": decided}, rules)
    final = "full" if promoted else decided

    assert decided == lane, reason
    if promotion is None:
        assert promoted is None, promoted
    else:
        assert promoted and promotion in promoted
    assert gates.select({"lane": final}, change, rules, has_tests=True) == selected


def test_forcing_fast_over_a_security_path_is_refused():
    rules = flask_ruleset()

    decided, _ = chief.decide_lane(facts("routes/__init__.py", kind="literal"), rules)

    assert decided == "full"
    assert chief._security_hit(["routes/__init__.py"], rules) == (
        "routes/__init__.py", "routes/**")


def test_a_fast_template_edit_raises_new_ui_literal_instead_of_ux():
    rules = flask_ruleset()
    change = {"base": "b", "head": "h", "commits": [], "tracked": ["templates/index.html"],
              "files": [{"path": "templates/index.html", "status": "M", "removed": [],
                         "content": "<button>Save changes</button>\n",
                         "added": [{"line": 1, "text": "<button>Save changes</button>"}]}]}

    selected = gates.select({"lane": "fast"}, change, rules, has_tests=True)
    verdict = constitution_gate.run(change, rules)

    assert "ux" not in selected
    assert [f["rule"] for f in verdict["findings"]] == ["constitution.new-ui-literal"]
