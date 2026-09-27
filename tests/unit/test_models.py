"""models.py — which models the account can reach, and the fallback (§6.2, §14)."""

from __future__ import annotations

from pathlib import Path

from taller import config, models


def test_load_probe_is_none_before_any_probe(tmp_home: Path):
    assert models.load_probe() is None


def test_probe_records_each_candidate_and_survives_a_failure(tmp_home: Path, stub_claude,
                                                              monkeypatch):
    monkeypatch.setenv("STUB_CLAUDE_FAIL_MODEL", "fable")

    result = models.probe(["sonnet", "fable"])

    assert result["models"]["sonnet"]["ok"] is True
    assert result["models"]["fable"]["ok"] is False and result["models"]["fable"]["error"]
    assert models.load_probe() == result
    assert models.reachable("sonnet", result) is True
    assert models.reachable("fable", result) is False
    assert models.reachable("opus", result) is None, "never probed is not the same as down"
    probed = [argv[argv.index("--model") + 1] for argv in stub_claude.calls()]
    assert probed == ["sonnet", "fable"]


def test_fallback_names_the_worker_model_unless_already_it(tmp_home: Path):
    cfg = config.load_hub_config()

    assert models.fallback_for("architect", cfg) == "sonnet"       # thinker -> worker
    assert models.fallback_for("implementer", cfg) is None          # already the worker
