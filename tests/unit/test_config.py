from pathlib import Path

import pytest
import yaml

from taller import config, paths
from taller.errors import ConfigError


def test_empty_hub_loads_with_shipped_defaults(tmp_home: Path):
    cfg = config.load_hub_config()
    assert cfg["language"] is None                      # spec 4.0 — never assumed
    assert cfg["billing"]["mode"] == "subscription"      # no key set, no key present
    assert cfg["model_aliases"]["worker"] == "sonnet"
    assert cfg["models"]["chief"] == "worker"
    assert cfg["effort"]["default"] == "low"
    assert cfg["weights"]["cache_read"] == 0.1
    assert cfg["cli_min_version"] == "2.1.74"


def test_hub_file_overrides_defaults(tmp_home: Path):
    paths.hub().mkdir(parents=True)
    paths.hub_config().write_text(
        yaml.safe_dump({"thresholds": {"max_file_lines": 400}}), encoding="utf-8"
    )
    cfg = config.load_hub_config()
    assert cfg["thresholds"]["max_file_lines"] == 400
    # Unnamed keys keep their default rather than disappearing.
    assert cfg["thresholds"]["max_function_lines"] == 80


def test_deep_merge_dicts_later_wins():
    base = {"a": {"x": 1, "y": 2}}
    over = {"a": {"y": 99}}
    assert config.deep_merge(base, over) == {"a": {"x": 1, "y": 99}}


def test_lists_replace_by_default():
    base = {"paths": {"ui": ["templates/**"]}}
    over = {"paths": {"ui": ["*.html"]}}
    assert config.deep_merge(base, over)["paths"]["ui"] == ["*.html"]


def test_security_sensitive_is_append_only():
    base = {"paths": {"security_sensitive": [".env*"]}}
    over = {"paths": {"security_sensitive": ["routes/**"]}}
    merged = config.deep_merge(base, over)
    assert merged["paths"]["security_sensitive"] == [".env*", "routes/**"]


def test_security_sensitive_cannot_be_narrowed():
    # A project that could drop a hub glob would make the mandatory security
    # gate optional (spec 4.4).
    base = {"paths": {"security_sensitive": [".env*", "database.py"]}}
    over = {"paths": {"security_sensitive": [".env*"]}}
    merged = config.deep_merge(base, over)
    assert "database.py" in merged["paths"]["security_sensitive"]


def test_security_sensitive_does_not_duplicate():
    base = {"paths": {"security_sensitive": [".env*"]}}
    over = {"paths": {"security_sensitive": [".env*", "x/**"]}}
    assert config.deep_merge(base, over)["paths"]["security_sensitive"] == [".env*", "x/**"]


def test_hub_sha_is_empty_when_the_hub_is_not_a_repo(tmp_home: Path):
    cfg = config.load_hub_config()
    assert cfg["hub_sha"] == ""      # the state a first-ever install is in


def test_security_sensitive_rejects_a_scalar(tmp_home: Path):
    # A string here would silently replace the floor (spec 4.4).
    with pytest.raises(ConfigError, match="append-only"):
        config.deep_merge(
            {"paths": {"security_sensitive": [".env*"]}},
            {"paths": {"security_sensitive": "billing/**"}},
        )


def test_resolve_model_maps_role_through_alias(tmp_home: Path):
    cfg = config.load_hub_config()
    assert config.resolve_model("chief", cfg) == "sonnet"
    assert config.resolve_model("architect", cfg) == "opus"
    assert config.resolve_model("scribe", cfg) == "haiku"


def test_resolve_effort_falls_back_to_default(tmp_home: Path):
    cfg = config.load_hub_config()
    assert config.resolve_effort("architect", cfg) == "high"
    assert config.resolve_effort("explorer", cfg) == "low"      # via "default"
    assert config.resolve_effort("nonexistent", cfg) == "low"   # never a KeyError


def test_malformed_yaml_is_a_clear_error(tmp_home: Path):
    paths.hub().mkdir(parents=True)
    paths.hub_config().write_text("this: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="taller.yml"):
        config.load_hub_config()


def test_non_suppressible_ships_empty(tmp_home: Path):
    """A fresh install forbids nothing extra; the owner adds to it (spec 4.5)."""
    assert config.load_hub_config()["non_suppressible"] == []


def test_non_suppressible_is_append_only():
    """A project may add a rule nobody may override; it may not remove one the hub
    declared. Configuration, not prose - an earlier draft kept this in never.md
    front matter, where a parser expecting it at line 1 would have read it as empty
    and silently made every rule suppressible."""
    merged = config.deep_merge(
        {"non_suppressible": ["brand.hardcoded-color"]},
        {"non_suppressible": ["size.file-too-long"]},
    )
    assert merged["non_suppressible"] == ["brand.hardcoded-color", "size.file-too-long"]


def test_non_suppressible_cannot_be_narrowed():
    merged = config.deep_merge(
        {"non_suppressible": ["brand.hardcoded-color", "constitution.layer-violation"]},
        {"non_suppressible": ["brand.hardcoded-color"]},
    )
    assert "constitution.layer-violation" in merged["non_suppressible"]


def test_non_suppressible_rejects_a_scalar():
    with pytest.raises(ConfigError, match="append-only"):
        config.deep_merge({"non_suppressible": []}, {"non_suppressible": "brand.x"})
