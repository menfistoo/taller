"""Usage told by job (phase G2, Task 3).

`by_model` says which model ran; it cannot say for what - the explorer and a
fixer may both run on the same model. `by_role` beside it records each job's own
usage, so "What it uses" can say where a thing's usage went. A ticket recorded
before this has no `by_role`, and it stays absent rather than starting partway:
half a breakdown would read as the whole one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import support
from taller import chief, config, discovery, inference, spend, tickets
from taller.prompter import ScriptedPrompter

from test_spend import on_main, result


@pytest.fixture
def project(tmp_home: Path, identity) -> Path:
    return support.new_project()


def test_each_job_is_counted_under_its_own_role(project):
    ticket = tickets.create(project, title="A thing", words="Do it.", kind="bug")
    cfg = config.load_hub_config()

    spend.fold(project, ticket["id"], result("claude-haiku-4-5", input=300), cfg, role="explorer")
    spend.fold(project, ticket["id"], result("claude-haiku-4-5", input=20), cfg, role="chief")
    spend.fold(project, ticket["id"], result("claude-opus-5-5", input=50), cfg, role="architect")

    block = on_main(project, ticket)
    assert block["by_role"]["explorer"]["input"] == 300
    assert block["by_role"]["chief"]["input"] == 20
    assert block["by_role"]["architect"]["input"] == 50
    assert block["by_model"]["claude-haiku-4-5"]["input"] == 320
    assert block["ran"] == {"explorer": "claude-haiku-4-5", "chief": "claude-haiku-4-5",
                            "architect": "claude-opus-5-5"}


def test_the_model_a_job_ran_on_last_is_the_one_remembered(project):
    ticket = tickets.create(project, title="A thing", words="Do it.", kind="bug")
    cfg = config.load_hub_config()

    spend.fold(project, ticket["id"], result("claude-opus-5-5"), cfg, role="architect")
    spend.fold(project, ticket["id"], result("claude-fable-5-1"), cfg, role="architect")

    assert on_main(project, ticket)["ran"]["architect"] == "claude-fable-5-1"


def test_a_ticket_from_before_has_no_by_role_and_nothing_breaks(project):
    ticket = tickets.create(project, title="A thing", words="Do it.", kind="bug")
    cfg = config.load_hub_config()
    spend.fold(project, ticket["id"], result(input=100), cfg)          # as recorded before

    spend.fold(project, ticket["id"], result(input=40), cfg, role="explorer")

    block = on_main(project, ticket)
    assert "by_role" not in block, "a breakdown that starts partway would mislead"
    assert block["by_model"]["claude-sonnet-5"]["input"] == 140


def test_the_chief_tells_fold_which_job_it_was(tmp_home, identity, stub_claude, monkeypatch,
                                                tmp_path):
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    project = support.new_project()
    from taller import cli
    assert cli.main(["models", "probe"], ScriptedPrompter({})) == 0
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"chief": [{"value": {
        "kind": "bug", "title": "Heading", "summary": "The heading."}}]}), encoding="utf-8")
    monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(script))
    ticket = tickets.create(project, title="x", words="The heading.", kind="feature",
                            named_by=None)

    chief.classify(project, int(ticket["id"]))

    assert set(on_main(project, ticket)["by_role"]) == {"chief"}
