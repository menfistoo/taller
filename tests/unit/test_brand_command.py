"""`taller brand new` — guide first, swatch before write, cancel writes nothing."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import support
from taller import brands, constitution, paths
from taller.commands import brand
from taller.prompter import ScriptedPrompter


@pytest.fixture(autouse=True)
def no_browser(monkeypatch: pytest.MonkeyPatch):
    opened = []
    monkeypatch.setattr(brand, "open_in_browser", opened.append)
    return opened


def hub_log() -> list[str]:
    completed = subprocess.run(["git", "-C", str(paths.hub()), "log", "--format=%s"],
                               capture_output=True, text=True)
    return completed.stdout.splitlines() if completed.returncode == 0 else []


def test_from_a_guide_pdf_the_proposal_is_reviewed_then_saved(
    tmp_home: Path, tmp_path: Path, identity, no_browser,
):
    pdf = support.make_pdf(tmp_path / "guide.pdf", ["Primary #1B365D", "Accent #C8A45C",
                                                    "Typeface: Inter"])
    prompter = ScriptedPrompter({
        "brand.slug": "harbour", "brand.start": "1", "brand.pdf": f'"{pdf}"',
        "brand.tokens": "", "brand.intent": "Calm navy; gold for the one action.",
        "brand.approve": "1",
    })

    assert brand.create(prompter) == "harbour"

    prompter.assert_all_used()
    assert constitution._resolve_brand("harbour")["tokens"] == {
        "--color-primary": "#1b365d", "--color-accent": "#c8a45c",
        "--font-body": '"Inter", sans-serif',
    }
    assert no_browser == [paths.swatch("harbour")], "the swatch was not shown before saving"
    assert hub_log() == ["brand: add harbour"]


def test_a_scanned_pdf_says_so_and_offers_the_other_starts(
    tmp_home: Path, tmp_path: Path, identity,
):
    scan = support.make_pdf(tmp_path / "scan.pdf", [])
    scratch = {f"brand.scratch.{name[2:]}": "" for name, _, _ in brand.SCRATCH}
    scratch.update({"brand.scratch.color-primary": "#1b365d",
                    "brand.scratch.color-accent": ("gold", "#c8a45c")})
    prompter = ScriptedPrompter({
        "brand.slug": "harbour", "brand.start": ("1", "4"), "brand.pdf": str(scan),
        **scratch, "brand.tokens": "", "brand.intent": "Calm.", "brand.approve": "1",
    })

    brand.create(prompter, open_page=False)

    assert any("text layer" in line for line in prompter.said)
    assert any("#1b365d" in line for line in prompter.said)
    assert any("written like #1b365d" in line for line in prompter.said)
    tokens = constitution._resolve_brand("harbour")["tokens"]
    assert tokens["--color-accent"] == "#c8a45c"
    assert tokens["--color-danger"] == "#dc3545"


def test_tokens_can_be_renamed_changed_dropped_and_added(tmp_home: Path, tmp_path: Path, identity):
    css = support.write(tmp_path / "site.css",
                        ":root { --blue: #1b365d; --junk: 1px; --gold: #c8a45c; }")
    prompter = ScriptedPrompter({
        "brand.slug": "harbour", "brand.start": "2", "brand.css": str(css),
        "brand.tokens": ("1", "2", "+", ""),
        "brand.token.name": ("--color-primary", "-", "--font-body"),
        "brand.token.value": ("", '"Inter";}', '"Inter", sans-serif'),
        "brand.intent": "Calm.", "brand.approve": "1",
    })

    brand.create(prompter, open_page=False)

    prompter.assert_all_used()
    assert constitution._resolve_brand("harbour")["tokens"] == {
        "--color-primary": "#1b365d", "--gold": "#c8a45c", "--font-body": '"Inter", sans-serif',
    }


def test_cancel_writes_nothing(tmp_home: Path, tmp_path: Path, identity):
    css = support.write(tmp_path / "site.css", ":root { --color-primary: #1b365d; }")

    result = brand.create(ScriptedPrompter({
        "brand.slug": "harbour", "brand.start": "2", "brand.css": str(css),
        "brand.tokens": "", "brand.intent": "Calm.", "brand.approve": "3",
    }), open_page=False)

    assert result is None
    assert brands.list_brands() == []
    assert hub_log() == []


def test_a_taken_or_invalid_name_is_asked_again(tmp_home: Path, tmp_path: Path, identity):
    support.make_brand("harbour")
    css = support.write(tmp_path / "site.css", ":root { --color-primary: #1b365d; }")
    prompter = ScriptedPrompter({
        "brand.slug": ("harbour", "Bad Name", "none", "reef"), "brand.start": "2",
        "brand.css": ("nowhere.css", str(css)), "brand.tokens": "",
        "brand.intent": "Calm.", "brand.approve": "1",
    })

    assert brand.create(prompter, open_page=False) == "reef"
    assert any("already has a brand" in line for line in prompter.said)
    assert any("no file at" in line for line in prompter.said)
