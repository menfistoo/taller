"""Spec 4.6, 3.1, 4.2.1 — the three generated artefacts.

All three renderers are `RuleSet -> bytes`, all pure, and all compared byte for
byte later: locally the tamper check re-resolves and compares, so an unstable
renderer would report a clean repository as modified - a BLOCKER on every
checkout. Byte stability is therefore asserted first, for each of them.

The invariant numbers are the plan's, task 14.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pytest
import yaml

import support

from taller import constitution, paths
from taller.errors import ConfigError

PROJECT_SLICES = {
    "product": "> What this does, who uses it, and what must never break.\n",
    "architecture": "> The layers of this project and what may import what.\n",
    "overrides": (
        "---\n"
        "overrides:\n"
        "  - rule:   size.file-too-long\n"
        '    reason: "Being split ticket by ticket."\n'
        "    until:  2026-12-31\n"
        "---\n"
        "\n"
        "> Suppressions in force, each with the decision that made it.\n"
    ),
}


def full_ruleset(**kwargs) -> tuple[Path, dict]:
    """A project with all nine slices provided, which is the widest index."""
    project = support.make_project(brand="acme", slices=PROJECT_SLICES, **kwargs)
    return project, constitution.resolve(project)


# --- invariant 1 -------------------------------------------------------------

def test_render_snapshot_is_byte_stable_across_two_calls(tmp_home: Path):
    """Spec 4.6 compares the committed snapshot against an in-memory re-render.
    Unsorted keys or a platform newline would make a clean checkout fail."""
    _, ruleset = full_ruleset()

    first = constitution.render_snapshot(ruleset)
    second = constitution.render_snapshot(ruleset)

    assert first == second
    assert isinstance(first, bytes)
    assert b"\r\n" not in first, "LF, so git cannot rewrite it under the check"
    assert first.endswith(b"\n")

    text = first.decode("utf-8")                     # raises if it is not UTF-8
    data = json.loads(text)
    assert text == json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


# --- invariant 2 -------------------------------------------------------------

def test_the_snapshot_carries_the_slice_text(tmp_home: Path):
    """CI cannot see the hub (spec 4.6), so the text has to travel. A snapshot
    that carried only paths would leave two of CI's three gates unable to run."""
    _, ruleset = full_ruleset()
    data = json.loads(constitution.render_snapshot(ruleset).decode("utf-8"))

    assert "Never commit a secret" in data["slices"]["never"]["text"]
    assert data["brand"]["tokens"]["--color-primary"] == "#1b365d"
    assert data["mode"] == "local"


# --- invariant 3 -------------------------------------------------------------

def test_a_loaded_snapshot_is_the_same_ruleset_in_ci_mode(tmp_home: Path):
    """`mode` is the one behavioural difference between a local and a CI run, and
    it travels inside the RuleSet so the gates stay pure (spec 4.4)."""
    project, ruleset = full_ruleset()
    support.write(paths.project_snapshot(project),
                  constitution.render_snapshot(ruleset).decode("utf-8"))

    loaded = constitution.load_snapshot(project)

    assert loaded["mode"] == "ci"
    assert loaded == {**ruleset, "mode": "ci"}


def test_load_snapshot_restores_an_until_as_a_date(tmp_home: Path):
    """JSON has no date, and `overrides.apply` compares `until` against today. A
    string arriving here would raise a TypeError inside the CI gate instead."""
    project, ruleset = full_ruleset()
    support.write(paths.project_snapshot(project),
                  constitution.render_snapshot(ruleset).decode("utf-8"))

    loaded = constitution.load_snapshot(project)
    assert loaded["overrides"][0]["until"] == date(2026, 12, 31)


# --- invariant 4 -------------------------------------------------------------

def test_render_index_is_byte_stable_and_lf(tmp_home: Path):
    _, ruleset = full_ruleset()

    first = constitution.render_index(ruleset)
    assert first == constitution.render_index(ruleset)
    assert b"\r\n" not in first
    assert first.endswith(b"\n")
    first.decode("utf-8")


def test_render_index_raises_rather_than_exceeding_its_budget(tmp_home: Path):
    """The 800-token briefing budget of criterion 6 is split explicitly: 600 for
    the index, 200 for the CLAUDE.md stub. Silently overrunning it would break
    the goal the phase is measured on, invisibly."""
    _, ruleset = full_ruleset()
    ruleset["slices"]["product"]["text"] = "> " + ("a very long sentence " * 200) + ".\n"

    with pytest.raises(ConfigError, match="600"):
        constitution.render_index(ruleset)


def test_the_index_is_inside_its_budget_and_estimate_tokens_is_pessimistic(tmp_home: Path):
    """There is no local tokenizer and a real count costs an API call, so the
    estimate is deliberately high: passing it means the true count is lower."""
    _, ruleset = full_ruleset()
    rendered = constitution.render_index(ruleset).decode("utf-8")

    assert constitution.estimate_tokens(rendered) <= constitution.INDEX_TOKEN_BUDGET
    assert constitution.estimate_tokens("a" * 7) == 2
    assert constitution.estimate_tokens("a" * 8) == math.ceil(8 / 3.5)


# --- invariants 5 and 6 ------------------------------------------------------

def test_the_index_collects_each_slices_first_blockquote_line_verbatim(tmp_home: Path):
    """Every module file is required to open with a `> ` summary (spec 3.1). The
    index is a routing map naming slices, so the summary is all it carries."""
    _, ruleset = full_ruleset()
    rendered = constitution.render_index(ruleset).decode("utf-8")

    for name, resolved in ruleset["slices"].items():
        summary = next(line[2:] for line in resolved["text"].splitlines()
                       if line.startswith("> "))
        assert summary in rendered, f"the {name} summary is missing"
        assert name in rendered


def test_the_index_routing_table_always_loads_stack_never_and_overrides(tmp_home: Path):
    """Both are a few lines, and a prohibition or a suppression the chief cannot
    see has no effect at read time (spec 3.1)."""
    _, ruleset = full_ruleset()
    rendered = constitution.render_index(ruleset).decode("utf-8")

    _, front, body = rendered.split("---\n", 2)
    routing = yaml.safe_load(front)["routing"]

    assert routing["always"] == ["stack", "never", "overrides"]
    # All nine slices of spec 4.3 appear in the table the chief parses.
    assert {name for row in routing.values() for name in row} == set(
        constitution.SLICE_NAMES
    )
    assert len(body.strip().splitlines()) <= 40, "spec 3.1: the prose is short"


# --- invariant 7 -------------------------------------------------------------

def test_render_tokens_is_a_verbatim_copy_behind_a_generated_header(tmp_home: Path):
    """The hub is outside the Docker image, so the browser cannot load the hub's
    file (spec 4.2.1). This is the copy the application links."""
    _, ruleset = full_ruleset()

    rendered = constitution.render_tokens(ruleset)
    assert rendered == constitution.render_tokens(ruleset)
    text = rendered.decode("utf-8")

    assert b"\r\n" not in rendered
    assert text.startswith("/*"), "a generated-file header, so nobody edits it"
    assert text.endswith(support.BRAND_TOKENS_CSS), "verbatim, byte for byte"
    assert str(paths.brands()) not in text, (
        "no absolute path: this file is committed, and the tamper check compares "
        "it on whatever machine checks out the repository"
    )

    project = support.make_project(name="plain", brand=None)
    assert constitution.render_tokens(constitution.resolve(project)) is None


def test_a_multi_module_slice_contributes_every_summary(tmp_home):
    """Spec 3.1: "concatenated in profile order". `conventions` is python then js
    for flask-sqlite, and taking only the first would silently drop the JavaScript
    conventions from the one file the chief reads on every session."""
    rs = constitution.resolve(support.make_project())
    text = constitution.render_index(rs).decode("utf-8")
    assert "Python" in text or "python" in text
    assert "JavaScript" in text or "browser JavaScript" in text


def test_the_index_still_fits_its_budget_with_every_summary(tmp_home):
    """The reason it is safe to honour spec 3.1 here: there is room."""
    rs = constitution.resolve(support.make_project())
    text = constitution.render_index(rs).decode("utf-8")
    estimate = constitution.estimate_tokens(text)
    assert estimate <= constitution.INDEX_TOKEN_BUDGET, estimate
    print(f"\nindex estimate: {estimate} of {constitution.INDEX_TOKEN_BUDGET} tokens")
