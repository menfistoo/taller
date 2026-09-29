"""`taller ci`: the three model-free gates, on GitHub's computers.

Spec 9.4 — only constitution, size and pytest; against the committed
`.taller/resolved.json`, never resolving; no hub, no secrets, no model. A push
that touches only ticket files exits at once. Anything that stops the gates
seeing the real change is an error (exit 2), never a quiet pass: a required
check that passes vacuously is worse than no check.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import support
from taller import cli, constitution, discovery

CLEAN = "h1 { color: var(--color-danger, inherit); }\n"
HEX = "h1 { color: #dc3545; }\n"


def git(repo: Path, *args: str) -> str:
    return support.git(repo, *args)


@pytest.fixture
def checkout(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    """A project as CI sees it: a checkout with a committed snapshot, and no hub."""
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    project = support.new_project()
    git(project, "checkout", "-q", "-b", "work")
    return project


def change(project: Path, text: str, message: str = "fix(ui): the heading colour") -> None:
    support.write(project / "static" / "css" / "app.css", text)
    git(project, "add", "--all")
    git(project, "commit", "-q", "-m", message)


def run_ci(project: Path, *extra: str, capsys=None) -> tuple[int, str]:
    code = cli.main(["ci", "--path", str(project), "--base", "main", *extra])
    return code, capsys.readouterr().out if capsys else ""


def test_a_clean_change_passes(checkout, capsys):
    change(checkout, CLEAN)

    code, out = run_ci(checkout, capsys=capsys)

    assert code == 0, out
    assert "constitution" in out and "pass" in out


def test_a_hardcoded_colour_fails_with_an_annotation(checkout, capsys):
    change(checkout, HEX)

    code, out = run_ci(checkout, capsys=capsys)

    assert code == 1
    assert out.startswith("::error file=static/css/app.css,line=1,")
    assert "brand.hardcoded-color" in out and "#dc3545" in out


def test_only_low_findings_still_pass(checkout, capsys, monkeypatch):
    from taller import gates
    from taller.gates import size as size_gate

    monkeypatch.setattr(size_gate, "run", lambda *a, **k: gates.verdict(
        "size", [gates.finding("size.duplicate-block", "app.py", 3, "twelve lines twice")], {}))
    change(checkout, CLEAN)

    code, out = run_ci(checkout, capsys=capsys)

    assert code == 0
    assert "::notice file=app.py,line=3," in out and "size.duplicate-block" in out


def test_a_ticket_file_only_push_exits_at_once(checkout, capsys, monkeypatch):
    from taller.gates import tests as tests_gate

    monkeypatch.setattr(tests_gate, "run", lambda *a, **k: pytest.fail("a gate ran"))
    support.write(checkout / ".taller" / "work" / "0001-x" / "notes.md", "a note\n")
    git(checkout, "add", "--all")
    git(checkout, "commit", "-q", "-m", "docs(ticket): a note")

    code, out = run_ci(checkout, capsys=capsys)

    assert code == 0 and "ticket files" in out


def test_mode_prints_full_or_ticket_files(checkout, capsys):
    change(checkout, CLEAN)
    assert run_ci(checkout, "--mode", capsys=capsys) == (0, "full\n")

    support.write(checkout / ".taller" / "work" / "0002-y" / "notes.md", "x\n")
    git(checkout, "add", "--all")
    git(checkout, "commit", "-q", "-m", "docs(ticket): y")
    git(checkout, "checkout", "-q", "-b", "only-tickets", "main")
    git(checkout, "cherry-pick", git(checkout, "rev-parse", "work").strip())

    assert cli.main(["ci", "--path", str(checkout), "--base", "main", "--head", "HEAD",
                     "--mode"]) == 0


def test_a_base_the_checkout_cannot_see_is_an_error_not_a_pass(checkout, capsys):
    change(checkout, HEX)

    code = cli.main(["ci", "--path", str(checkout), "--base", "0" * 40])

    out = capsys.readouterr().out
    assert code == 2 and "could not" in out.lower()


def test_a_missing_snapshot_is_an_error(checkout, capsys):
    change(checkout, CLEAN)
    (checkout / ".taller" / "resolved.json").unlink()
    git(checkout, "add", "--all")
    git(checkout, "commit", "-q", "-m", "chore: drop the snapshot")

    code, out = run_ci(checkout, capsys=capsys)

    assert code == 2 and "taller resolve" in out


def test_a_branch_carrying_the_snapshot_is_an_error(checkout, capsys):
    snapshot = checkout / ".taller" / "resolved.json"
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    data["hub_sha"] = "0" * 40
    support.write(snapshot, json.dumps(data))
    git(checkout, "add", "--all")
    git(checkout, "commit", "-q", "-m", "chore: edit the snapshot")

    code, out = run_ci(checkout, capsys=capsys)

    assert code == 2 and "resolved.json" in out


def test_ci_needs_no_hub_and_no_key(checkout, capsys, monkeypatch, tmp_path):
    change(checkout, CLEAN)
    monkeypatch.setenv("HOME", str(tmp_path / "nowhere"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "nowhere"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(constitution, "resolve",
                        lambda *a, **k: pytest.fail("CI resolved instead of loading"))

    code, out = run_ci(checkout, capsys=capsys)

    assert code == 0, out
