"""billing.py — the mode, the cost, and how old the price table is (§5.2, §7.5)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from taller import billing, config, hub


def cfg_with(mode: str | None) -> dict:
    cfg = config.load_hub_config()
    cfg["billing"]["mode"] = mode
    return cfg


def test_mode_prefers_configured_then_detected(tmp_home: Path, monkeypatch):
    assert billing.mode(cfg_with(None)) == "subscription"
    assert billing.mode(cfg_with("api")) == "api"


def test_mismatch_names_both(tmp_home: Path, monkeypatch):
    assert billing.mismatch() is None
    hub.update_config({"billing": {"mode": "subscription"}})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    sentence = billing.mismatch()

    assert "subscription" in sentence and "api" in sentence


def test_cost_is_none_off_api(tmp_home: Path):
    by_model = {"claude-sonnet-5": {"input": 2_000_000, "cache_write": 0, "cache_read": 0,
                                    "output": 0}}

    assert billing.cost(by_model, cfg_with("subscription")) == (None, False)


def test_cost_on_api_prices_by_reported_id(tmp_home: Path):
    by_model = {"claude-sonnet-5": {"input": 2_000_000, "cache_write": 0, "cache_read": 0,
                                    "output": 0}}

    assert billing.cost(by_model, cfg_with("api")) == (4.0, False)


def test_an_unpriced_model_makes_cost_partial(tmp_home: Path):
    by_model = {
        "claude-sonnet-5": {"input": 1_000_000, "cache_write": 0, "cache_read": 0, "output": 0},
        "claude-mystery-9": {"input": 1_000_000, "cache_write": 0, "cache_read": 0, "output": 0},
    }

    assert billing.cost(by_model, cfg_with("api")) == (2.0, True)


def test_pricing_age(tmp_home: Path):
    cfg = config.load_hub_config()
    cfg["pricing"] = {**cfg["pricing"], "as_of": "2026-06-24"}

    assert billing.pricing_age_days(cfg, date(2026, 9, 28)) == 96
