"""spend.py — per-dispatch usage folded into the ticket, weighted, with a budget (§7.5)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import support
from taller import config, inference, spend, tickets


@pytest.fixture
def project(tmp_home: Path, identity) -> Path:
    return support.new_project()


def result(model: str = "claude-sonnet-5", *, input: int = 100, output: int = 50,
           cost_usd: float | None = None) -> inference.Result:
    return inference.Result(ok=True, value="ok", session_id="s", cost_usd=cost_usd,
                            usage=[inference.UsageRecord(model=model, input=input,
                                                         output=output)])


def api_cfg() -> dict:
    cfg = config.load_hub_config()
    cfg["billing"]["mode"] = "api"
    return cfg


def on_main(project: Path, ticket: dict) -> dict:
    raw = tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/status.yml")
    return yaml.safe_load(raw)["spend"]


def test_weighted_matches_the_spec_example(tmp_home: Path):
    by_model = {
        "claude-haiku-4-5": {"input": 1200, "cache_write": 9000, "cache_read": 31000, "output": 3100},
        "claude-sonnet-5": {"input": 2400, "cache_write": 22000, "cache_read": 64000, "output": 12600},
    }

    assert spend.weighted(by_model, config.load_hub_config()["weights"]) == 130_350


def test_fold_accumulates_by_reported_model_across_dispatches(project: Path):
    ticket = tickets.create(project, title="First", words="w", kind="idea")
    cfg = config.load_hub_config()

    spend.fold(project, ticket["id"], result(), cfg)
    block = spend.fold(project, ticket["id"], result(), cfg)

    assert block["by_model"]["claude-sonnet-5"] == {"input": 200, "cache_write": 0,
                                                    "cache_read": 0, "output": 100}
    assert (block["total_tokens"], block["weighted_tokens"]) == (300, 700)
    assert block["cost"] is None and block["partial"] is False
    assert on_main(project, ticket) == block


def test_cost_usd_is_never_summed(project: Path):
    ticket = tickets.create(project, title="First", words="w", kind="idea")

    spend.fold(project, ticket["id"], result(cost_usd=0.5), api_cfg())
    block = spend.fold(project, ticket["id"], result(cost_usd=0.9), api_cfg())

    # 200 input × $2/M + 100 output × $10/M - from usage, not from 0.5 + 0.9.
    assert block["cost"] == pytest.approx(0.0014)


def test_no_usage_marks_partial(project: Path):
    ticket = tickets.create(project, title="First", words="w", kind="idea")
    empty = inference.Result(ok=True, value="ok", session_id="s", usage=[])

    assert spend.fold(project, ticket["id"], empty, config.load_hub_config())["partial"] is True


def test_fold_on_api_with_an_unpriced_model_is_partial(project: Path):
    ticket = tickets.create(project, title="First", words="w", kind="idea")

    block = spend.fold(project, ticket["id"], result("claude-mystery-9"), api_cfg())

    assert block["partial"] is True and block["cost"] == 0.0


@pytest.mark.parametrize("weighted, verdict", [(1_199_999, "ok"), (1_200_000, "warn"),
                                               (3_999_999, "warn"), (4_000_000, "stop")])
def test_budget_thresholds(tmp_home: Path, weighted: int, verdict: str):
    ticket = {"spend": {"weighted_tokens": weighted}}

    assert spend.budget(ticket, config.load_hub_config()) == verdict
