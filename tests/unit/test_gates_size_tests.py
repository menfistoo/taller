"""The size and tests gates. Spec 9.1, 9.7; Review Focus 1 (a gate that cannot run)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import support
from taller import gates
from taller.gates import diff as diffs
from taller.gates import size
from taller.gates import tests as tests_gate

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "broken-app"
THRESHOLDS = {"max_file_lines": 800, "max_function_lines": 80, "dup_block_lines": 12,
              "min_coverage_pct": 0}


def ruleset(**thresholds) -> dict:
    return {"thresholds": {**THRESHOLDS, **thresholds}, "paths": {"tests_dir": "tests"}}


def change(files: dict[str, str], added: dict[str, list[int]] | None = None) -> dict:
    """A Diff by hand; `added` limits which lines count as added (default: all)."""
    out = []
    for path, text in files.items():
        lines = text.splitlines()
        wanted = (added or {}).get(path, range(1, len(lines) + 1))
        out.append({"path": path, "status": "M", "content": text, "removed": [],
                    "added": [{"line": n, "text": lines[n - 1]} for n in wanted]})
    return {"base": "b", "head": "h", "commits": [], "tracked": sorted(files), "files": out}


def function(name: str, body_lines: int) -> str:
    return f"def {name}():\n" + "".join(f"    x{n} = {n}\n" for n in range(body_lines))


def found(verdict: dict, rule: str) -> list[dict]:
    return [f for f in verdict["findings"] if f["rule"] == rule]


# --- size ------------------------------------------------------------------------------

def test_a_long_function_in_the_change_is_flagged_and_an_untouched_one_is_not():
    text = function("old", 90) + "\n\n" + function("new", 90)
    new_start = text.splitlines().index("def new():") + 1

    verdict = size.run(change({"a.py": text}, {"a.py": [new_start + 3]}), ruleset())

    hits = found(verdict, "size.function-too-long")
    assert [(h["line"], h["severity"]) for h in hits] == [(new_start, "MEDIUM")]
    assert "new" in hits[0]["message"] and "91" in hits[0]["message"]
    assert verdict["metrics"]["longest_function"] == 91


def test_a_function_at_the_limit_is_not_flagged():
    verdict = size.run(change({"a.py": function("ok", 79)}), ruleset())

    assert found(verdict, "size.function-too-long") == []


def test_a_file_over_the_limit():
    text = "".join(f"x{n} = {n}\n" for n in range(801))

    verdict = size.run(change({"big.py": text, "small.py": "x = 1\n"}), ruleset())

    hits = found(verdict, "size.file-too-long")
    assert [(h["file"], h["severity"]) for h in hits] == [("big.py", "MEDIUM")]
    assert "801" in hits[0]["message"]


BLOCK = [f"total_{n} = compute(rows, {n})" for n in range(12)]


def test_duplicate_blocks_by_the_normalisation():
    noisy = []
    for n, line in enumerate(BLOCK):
        noisy.append("    " + line.replace(" = ", "   =   ") + ("  # why" if n == 3 else ""))
        if n == 5:
            noisy += ["", "    # a comment on its own line"]
    text = "def a(rows):\n" + "".join(f"    {line}\n" for line in BLOCK) + "\n\n" \
        + "def b(rows):\n" + "".join(f"{line}\n" for line in noisy)

    verdict = size.run(change({"a.py": text}), ruleset())

    hits = found(verdict, "size.duplicate-block")
    assert len(hits) == 1 and hits[0]["severity"] == "LOW"


def test_a_renamed_identifier_is_not_a_duplicate():
    other = [line.replace("rows", "items") for line in BLOCK]
    text = "".join(f"{line}\n" for line in BLOCK) + "\n" + "".join(f"{line}\n" for line in other)

    assert found(size.run(change({"a.py": text}), ruleset()), "size.duplicate-block") == []


def test_a_block_copied_from_an_untouched_file_is_found_through_the_tree():
    block = "".join(f"{line}\n" for line in BLOCK)
    diff = change({"new.py": "import x\n" + block})
    tree = change({"new.py": "import x\n" + block, "old.py": block})

    hits = found(size.run(diff, ruleset(), tree=tree), "size.duplicate-block")

    assert [(h["file"], h["line"]) for h in hits] == [("new.py", 2)]
    assert "old.py:1" in hits[0]["message"]


def test_a_duplicate_outside_the_added_lines_is_not_the_changes_doing():
    block = "".join(f"{line}\n" for line in BLOCK)
    text = block + "\n" + block + "extra = 1\n"
    last = len(text.splitlines())

    verdict = size.run(change({"a.py": text}, {"a.py": [last]}), ruleset())

    assert found(verdict, "size.duplicate-block") == []


def test_an_unparseable_python_file_is_skipped_with_a_note():
    verdict = size.run(change({"a.py": "def broken(:\n"}), ruleset())

    assert verdict["result"] == "pass" and verdict["metrics"]["skipped"] == ["a.py"]


def test_broken_app_size_rows(tmp_path: Path, identity):
    repo = tmp_path / "broken-app"
    shutil.copytree(FIXTURE, repo)
    support.make_repo(repo, {})
    subprocess.run(["git", "-C", str(repo), "add", "--all"], check=True)

    verdict = size.scan(diffs.tree(repo), ruleset(max_file_lines=100))

    by_rule = {(f["rule"], f["file"], f["severity"]) for f in verdict["findings"]}
    assert ("size.function-too-long", "long_module.py", "MEDIUM") in by_rule
    assert ("size.duplicate-block", "long_module.py", "LOW") in by_rule
    assert ("size.file-too-long", "long_module.py", "MEDIUM") in by_rule
    assert len(found(verdict, "size.duplicate-block")) == 1


# --- tests -----------------------------------------------------------------------------

def project(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "project"
    for relative, text in files.items():
        support.write(root / relative, text)
    return root


def test_passing_suite_passes_with_metrics(tmp_path: Path):
    root = project(tmp_path, {"tests/test_a.py": "def test_one():\n    pass\n\n"
                                                 "def test_two():\n    pass\n"})

    verdict = tests_gate.run(root, ruleset())

    assert (verdict["gate"], verdict["result"], verdict["findings"]) == ("tests", "pass", [])
    assert verdict["metrics"]["tests_run"] == 2 and verdict["metrics"]["tests_passed"] == 2
    assert verdict["metrics"]["duration_s"] >= 0


def test_a_failing_test_is_named(tmp_path: Path):
    root = project(tmp_path, {"tests/test_a.py": "def test_good():\n    pass\n\n"
                                                 "def test_bad():\n    assert 1 == 2\n"})

    verdict = tests_gate.run(root, ruleset())

    hits = found(verdict, "tests.failed")
    assert verdict["result"] == "fail"
    assert [(h["file"], h["severity"]) for h in hits] == [("tests/test_a.py", "BLOCKER")]
    assert "tests/test_a.py::test_bad" in hits[0]["message"]
    assert verdict["metrics"]["tests_run"] == 2 and verdict["metrics"]["tests_passed"] == 1


def test_no_tests_is_a_pass_with_zero(tmp_path: Path):
    root = project(tmp_path, {"app.py": "x = 1\n"})

    verdict = tests_gate.run(root, ruleset())

    assert verdict["result"] == "pass" and verdict["metrics"]["tests_run"] == 0


def test_a_suite_that_cannot_run_is_an_error_not_a_pass(tmp_path: Path):
    root = project(tmp_path, {"tests/conftest.py": "def broken(:\n",
                              "tests/test_a.py": "def test_one():\n    pass\n"})

    verdict = tests_gate.run(root, ruleset())

    assert verdict["result"] == "error" and verdict["findings"] == []
    assert "conftest" in verdict["error"]
    escalated = gates.errors([verdict])
    assert [(e["rule"], e["severity"]) for e in escalated] == [("tests.error", "BLOCKER")]
    assert gates.route(escalated)["escalate"] == escalated


def test_a_venv_without_an_interpreter_is_an_error(tmp_path: Path):
    root = project(tmp_path, {".venv/pyvenv.cfg": "home = nowhere\n",
                              "tests/test_a.py": "def test_one():\n    pass\n"})

    verdict = tests_gate.run(root, ruleset())

    assert verdict["result"] == "error" and ".venv" in verdict["error"]


def test_a_suite_that_hangs_is_an_error(tmp_path: Path):
    root = project(tmp_path, {"tests/test_a.py": "import time\n\n"
                                                 "def test_slow():\n    time.sleep(60)\n"})

    verdict = tests_gate.run(root, ruleset(), timeout_s=3)

    assert verdict["result"] == "error" and "3 s" in verdict["error"]


def test_coverage_is_measured_only_when_a_minimum_is_set(tmp_path: Path):
    pytest.importorskip("pytest_cov")
    root = project(tmp_path, {"app.py": "def used():\n    return 1\n\n"
                                        "def unused():\n    return 2\n",
                              "tests/test_a.py": "import app\n\n"
                                                 "def test_used():\n    assert app.used() == 1\n"})

    off = tests_gate.run(root, ruleset())
    on = tests_gate.run(root, ruleset(min_coverage_pct=95))

    assert "coverage_pct" not in off["metrics"]
    assert on["metrics"]["coverage_pct"] < 95
    assert [h["severity"] for h in found(on, "tests.coverage-below-minimum")] == ["MEDIUM"]
