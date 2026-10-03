"""The price list knows the models that actually run (phase G2, Task 2).

Ticket 0001 on Taller itself ran `claude-haiku-4-5`, `claude-opus-5-5` and
`claude-sonnet-5-5`; the shipped table priced none of the 5.5 models, so on API
billing its cost was a lower bound with most of the work missing. The prices are
Anthropic's published ones, read on the day in `as_of` - never inferred from the
older entries. Opus 5.5 and Fable 5.1 read their cache for less than the usual
tenth of the input price, so the table carries that price where it differs.
"""

from __future__ import annotations

from taller import billing, config, doctor, tickets

import support

RAN_ON_TICKET_0001 = ("claude-haiku-4-5", "claude-opus-5-5", "claude-sonnet-5-5")


def api() -> dict:
    cfg = config.load_hub_config()
    cfg["billing"] = {"mode": "api"}
    return cfg


def test_every_model_that_ran_on_ticket_0001_is_priced(tmp_home):
    pricing = config.SHIPPED_DEFAULTS["pricing"]

    assert all(model in pricing for model in RAN_ON_TICKET_0001)
    assert pricing["claude-opus-5-5"] == {"input": 4.00, "output": 20.00, "cache_read": 0.20}
    assert pricing["claude-sonnet-5-5"] == {"input": 2.00, "output": 10.00}
    assert pricing["as_of"] == "2026-10-01"


def test_a_cache_read_is_priced_as_its_model_prices_it(tmp_home):
    million = {"input": 0, "cache_write": 0, "cache_read": 1_000_000, "output": 0}

    opus, _ = billing.cost({"claude-opus-5-5": million}, api())
    sonnet, _ = billing.cost({"claude-sonnet-5-5": million}, api())

    assert (opus, sonnet) == (0.20, 0.20)


def test_a_dated_model_id_finds_its_price(tmp_home):
    tokens = {"input": 1_000_000, "cache_write": 0, "cache_read": 0, "output": 0}

    figure, partial = billing.cost({"claude-haiku-4-5-20251001": tokens}, api())

    assert (figure, partial) == (1.0, False)


def test_doctor_names_an_unpriced_model_that_ran(tmp_home, identity, stub_claude, monkeypatch):
    from taller import discovery

    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    project = support.new_project()
    ticket = tickets.create(project, title="A thing", words="Do it.", kind="bug")
    ticket = tickets.load(project, int(ticket["id"]))
    ticket["spend"] = {"by_model": {"claude-mystery-9": {"input": 10, "cache_write": 0,
                                                          "cache_read": 0, "output": 1}},
                       "total_tokens": 11, "weighted_tokens": 15, "cost": None,
                       "partial": False, "sessions": []}
    tickets.write(project, ticket, "ticket 0001: spend")

    found = next(c for c in doctor.run_checks() if "price list" in c.name)

    assert "claude-mystery-9" in found.detail
    assert "only matters" in found.detail
    assert found.status == doctor.PASS          # a warning: subscription costs nothing extra
