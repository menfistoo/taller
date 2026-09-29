"""Criteria 1 and 5 (spec 16, 15.6): Taller ships knowing nothing about anyone."""

from __future__ import annotations

from pathlib import Path

import support
from taller import brands, catalogue, cli, config, paths, registry
from taller.prompter import ScriptedPrompter



def assert_hub_is_empty() -> None:
    assert config.load_hub_config()["language"] is None
    assert brands.list_brands() == []
    assert catalogue.installed_profiles() == []
    assert not paths.modules().exists() or not any(paths.modules().rglob("*.md"))
    assert registry.list_projects() == []


def test_a_fresh_hub_is_empty_before_and_after_doctor(tmp_home: Path, stub_claude):
    assert_hub_is_empty()

    assert cli.main(["doctor"], ScriptedPrompter({})) == 0

    assert_hub_is_empty()
    assert not paths.hub().exists(), "doctor wrote into the hub"


def test_no_shipped_file_names_its_owner_or_their_business(tmp_home: Path):
    """Every tracked file, including the design documents: the repository is public.

    `tmp_home` so the scan uses an empty hub rather than this machine's own list -
    the result must not depend on whose computer runs it.
    """
    words = support.vocabulary_words()
    assert words, "no word list: the scan would prove nothing"

    assert support.scan_tracked_files(words) == []
