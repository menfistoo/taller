"""Nothing in this repository names its owner, so it can be published.

Spec 15.6 and criterion 5 promised the *shipped* files knew nothing about
anyone. Making the repository public raises the bar: the design documents and
the word list itself are published too. So the owner's real list lives in her
hub, where Taller still checks against it and GitHub never sees it, and the
repository keeps a short generic example.
"""

from __future__ import annotations

from pathlib import Path

import support
from taller import hub, paths

REPO = Path(__file__).resolve().parents[2]
SHIPPED_LIST = REPO / "tests" / "domain_vocabulary.txt"


def test_the_shipped_list_is_made_up(tmp_home: Path):
    """The example words appear nowhere, so the check has something to prove and
    the list itself gives nothing away. Her real words live in her hub."""
    words = support.words_in(SHIPPED_LIST)

    assert words, "the example list must still hold words, or it checks nothing"
    assert support.scan_tracked_files(words) == []


def test_the_owners_own_list_lives_in_her_hub(tmp_home: Path):
    path = paths.domain_vocabulary()

    assert path.parent == paths.hub() and path.name == "domain_vocabulary.txt"
    assert "domain_vocabulary.txt" in hub.GITIGNORE


def test_the_repository_names_no_owner():
    """Not `tmp_home`: on her machine this reads her hub list, so the scan covers
    her real words. In a fresh clone there is no hub and the example list is all
    there is - which is why no test may write one of her words down."""
    found = support.scan_tracked_files(support.vocabulary_words())

    assert found == []


def test_a_word_from_the_hub_list_is_scanned_too(tmp_home: Path):
    # Built rather than written: this file is scanned like every other now, so a
    # word in the list must not appear in it literally.
    word = "north" + "shore"
    paths.hub().mkdir(parents=True, exist_ok=True)
    paths.domain_vocabulary().write_text(f"# mine\n{word}\n", encoding="utf-8")

    assert word in support.vocabulary_words()
    assert support.scan_tracked_files(support.vocabulary_words()) == []


def test_the_design_documents_are_scanned_now():
    assert not [p for p in support.VOCABULARY_EXEMPT if p.startswith("docs/")]
    assert "tests/fixtures/" in support.VOCABULARY_EXEMPT
