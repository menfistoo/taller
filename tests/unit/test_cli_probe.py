import pytest

from taller import cli_probe
from taller.errors import ConfigError

HELP_WITH_EVERYTHING = """
  -p, --print
  --output-format <format>
  --json-schema <schema>
  --append-system-prompt <prompt>
  --resume [sessionId]
  --session-id <uuid>
  --add-dir <directories...>
  --allowedTools, --allowed-tools <tools...>
  --disallowedTools, --disallowed-tools <tools...>
  --agents <json>
  --model <model>
  --permission-mode <mode>
  --permission-prompts <mode>
  --bare
"""

HELP_AS_SHIPPED_ON_2_1_74 = HELP_WITH_EVERYTHING.replace(
    "  --permission-prompts <mode>\n", ""
).replace("  --bare\n", "")


def test_all_required_flags_present_passes():
    report = cli_probe.check_flags(HELP_AS_SHIPPED_ON_2_1_74)
    assert report.ok
    assert report.missing_required == []


def test_optional_flags_are_reported_but_do_not_fail():
    report = cli_probe.check_flags(HELP_AS_SHIPPED_ON_2_1_74)
    assert set(report.missing_optional) == {"--permission-prompts", "--bare"}
    assert report.ok


def test_a_missing_required_flag_fails():
    help_text = HELP_AS_SHIPPED_ON_2_1_74.replace("  --json-schema <schema>\n", "")
    report = cli_probe.check_flags(help_text)
    assert not report.ok
    assert report.missing_required == ["--json-schema"]


def test_version_is_parsed():
    assert cli_probe.parse_version("2.1.74 (Claude Code)") == (2, 1, 74)


def test_version_comparison():
    assert cli_probe.version_at_least((2, 1, 74), "2.1.74")
    assert cli_probe.version_at_least((2, 2, 0), "2.1.74")
    assert not cli_probe.version_at_least((2, 1, 73), "2.1.74")


def test_supports_rejects_a_flag_it_has_never_heard_of():
    """An ungated version returned True for anything, so a typo in a caller
    silently became "supported" and got passed to the CLI."""
    report = cli_probe.check_flags(HELP_AS_SHIPPED_ON_2_1_74)
    assert report.supports("--json-schema") is True
    assert report.supports("--permission-prompts") is False
    with pytest.raises(ValueError, match="not a flag Taller knows about"):
        report.supports("--totally-made-up")


def test_version_at_least_rejects_a_malformed_minimum():
    """cli_min_version is owner-editable, so a typo must be a clear error rather
    than a TypeError from an unchecked comparison."""
    with pytest.raises(ConfigError, match="three-part version"):
        cli_probe.version_at_least((2, 1, 74), "2.1")


def test_an_unknown_observed_version_satisfies_no_floor():
    assert cli_probe.version_at_least(None, "2.1.74") is False


def test_parse_version_is_anchored():
    """Unanchored, a banner like "node 20.11.1, claude 2.1.74" gave the wrong
    tool's version."""
    assert cli_probe.parse_version("2.1.74 (Claude Code)") == (2, 1, 74)
    assert cli_probe.parse_version("node 20.11.1, claude 2.1.74") is None
