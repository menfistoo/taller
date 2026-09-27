"""Criteria 1 and 5 (spec 16, 15.6): Taller ships knowing nothing about anyone."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from taller import brands, catalogue, cli, config, paths, registry
from taller.prompter import ScriptedPrompter

REPO = Path(__file__).resolve().parents[2]
VOCABULARY = REPO / "tests" / "domain_vocabulary.txt"
# Files allowed to contain the words: the list itself, fixtures, the design
# documents (they cite a real estate as evidence, Appendix A, and do not ship),
# and the catalogue test that keeps its own list of generic lines of business.
EXEMPT_PREFIXES = ("docs/", "tests/fixtures/")
EXEMPT_FILES = {"tests/domain_vocabulary.txt", "tests/unit/test_catalogue_content.py"}


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


def test_no_shipped_file_names_its_owner_or_their_business():
    listed = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True,
                            text=True, encoding="utf-8")
    if listed.returncode != 0:
        pytest.skip("not a git checkout; the scan covers tracked files")
    words = [line.strip() for line in VOCABULARY.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    pattern = re.compile(r"(?<!\w)(" + "|".join(re.escape(w) for w in words) + r")(?!\w)",
                         re.IGNORECASE)

    found = []
    for relative in listed.stdout.splitlines():
        if relative in EXEMPT_FILES or relative.startswith(EXEMPT_PREFIXES):
            continue
        try:
            text = (REPO / relative).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue                                   # binary: nothing to read
        found += [f"{relative}: {m.group(0)}" for m in pattern.finditer(text)]

    assert found == []
