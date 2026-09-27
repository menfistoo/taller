"""brands.py — propose a palette from a guide, a stylesheet or a logo; write it.

Spec 4.2. Extractors propose and never decide; `write` is the only writer, and
what it writes must read back through the resolver unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

import support
from taller import brands, constitution, paths
from taller.errors import ConfigError


# --- from_pdf ----------------------------------------------------------------

def test_pdf_colours_are_collected_normalised_and_ranked(tmp_home: Path, tmp_path: Path):
    pdf = support.make_pdf(tmp_path / "guide.pdf", [
        "Secondary #C8A45C",
        "Primary #1B365D - use for all chrome",
        "Primary again: #1b365d",
        "Short form #FFF on dark",
        "Pantone 2767 C / HEX #1B365D",
    ])

    proposal = brands.from_pdf(pdf)

    assert proposal["source"] == "pdf"
    hexes = [colour["hex"] for colour in proposal["colours"]]
    # Count first (the navy is declared three times), then first appearance.
    assert hexes == ["#1b365d", "#c8a45c", "#ffffff"]
    assert proposal["colours"][0]["count"] == 3


def test_pdf_cmyk_values_are_converted(tmp_home: Path, tmp_path: Path):
    pdf = support.make_pdf(tmp_path / "guide.pdf", ["Orange CMYK C 0 M 50 Y 100 K 0"])

    hexes = [colour["hex"] for colour in brands.from_pdf(pdf)["colours"]]

    assert hexes == ["#ff8000"]


def test_pdf_fonts_come_from_labels_and_from_embedded_resources(tmp_home: Path, tmp_path: Path):
    pdf = support.make_pdf(
        tmp_path / "guide.pdf",
        ["Typeface: Playfair Display", "Font: Inter"],
        fonts=("Helvetica", "ABCDEF+Montserrat-Bold", "GHIJKL+Montserrat-Regular"),
    )

    fonts = brands.from_pdf(pdf)["fonts"]

    assert fonts[:2] == ["Playfair Display", "Inter"]
    assert "Montserrat" in fonts
    assert fonts.count("Montserrat") == 1, "subset prefix and style suffix not stripped"


def test_a_pdf_with_no_text_layer_proposes_nothing_and_says_so(tmp_home: Path, tmp_path: Path):
    pdf = support.make_pdf(tmp_path / "scan.pdf", [])

    proposal = brands.from_pdf(pdf)

    assert proposal["colours"] == []
    assert any("text layer" in note for note in proposal["notes"])


def test_a_file_that_is_not_a_pdf_is_a_clear_error(tmp_home: Path, tmp_path: Path):
    bogus = support.write(tmp_path / "guide.pdf", "not a pdf at all")

    with pytest.raises(ConfigError, match="guide.pdf"):
        brands.from_pdf(bogus)


# --- from_css ----------------------------------------------------------------

def test_css_custom_properties_in_order_last_declaration_wins(tmp_home: Path, tmp_path: Path):
    css = support.write(tmp_path / "site.css", """
:root {
  --color-primary: #1B365D;
  --font-body: "Inter", sans-serif;
}
body { color: red; }
:root { --color-primary: #223344; --space-2: 8px; }
""")

    tokens = brands.from_css(css)

    assert list(tokens) == ["--color-primary", "--font-body", "--space-2"]
    assert tokens["--color-primary"] == "#223344"
    assert tokens["--font-body"] == '"Inter", sans-serif'


# --- from_image --------------------------------------------------------------

def test_a_raster_logo_ranks_colours_by_area_and_ignores_transparency(
    tmp_home: Path, tmp_path: Path,
):
    image = Image.new("RGBA", (10, 10), (0, 0, 0, 0))          # transparent field
    for x in range(10):
        for y in range(6):
            image.putpixel((x, y), (27, 54, 93, 255))           # 60 px navy
    for x in range(10):
        for y in range(6, 8):
            image.putpixel((x, y), (200, 164, 92, 255))         # 20 px gold
    logo = tmp_path / "logo.png"
    image.save(logo)

    hexes = [colour["hex"] for colour in brands.from_image(logo)["colours"]]

    assert hexes[:2] == ["#1b365d", "#c8a45c"]
    assert "#000000" not in hexes, "transparent pixels were counted"


def test_an_svg_logo_is_read_from_its_literal_colours(tmp_home: Path, tmp_path: Path):
    svg = support.write(tmp_path / "logo.svg", """<svg xmlns="http://www.w3.org/2000/svg">
<rect fill="#1B365D"/><circle fill="#1b365d" stroke="#C8A45C"/>
<stop stop-color="#abc"/></svg>""")

    hexes = [colour["hex"] for colour in brands.from_image(svg)["colours"]]

    assert hexes == ["#1b365d", "#c8a45c", "#aabbcc"]


# --- propose_tokens ----------------------------------------------------------

def test_a_proposal_becomes_named_tokens():
    proposal = {
        "source": "pdf", "notes": [],
        "colours": [{"hex": h, "count": 1, "first": i}
                    for i, h in enumerate(["#111111", "#222222", "#333333"])],
        "fonts": ["Playfair Display", "Inter"],
    }

    tokens = brands.propose_tokens(proposal)

    assert tokens == {
        "--color-primary": "#111111",
        "--color-accent": "#222222",
        "--color-3": "#333333",
        "--font-body": '"Playfair Display", sans-serif',
        "--font-heading": '"Inter", sans-serif',
    }


# --- write -------------------------------------------------------------------

TOKENS = {"--color-primary": "#1b365d", "--font-body": '"Inter", sans-serif'}


def test_a_written_brand_resolves_to_the_same_tokens(tmp_home: Path):
    folder = brands.write("harbour", TOKENS, "Navy chrome, one gold call to action.")

    assert folder == paths.brands() / "harbour"
    assert constitution._resolve_brand("harbour")["tokens"] == TOKENS


def test_written_files_are_lf_and_brand_md_opens_with_a_summary(tmp_home: Path):
    folder = brands.write("harbour", TOKENS, "Navy chrome.\nGold for one call to action.")

    assert b"\r" not in (folder / "tokens.css").read_bytes()
    prose = (folder / "brand.md").read_text(encoding="utf-8")
    assert prose.splitlines()[0].startswith("> ")


def test_an_existing_brand_is_not_overwritten_unless_asked(tmp_home: Path):
    brands.write("harbour", TOKENS, "First.")

    with pytest.raises(ConfigError, match="already exists"):
        brands.write("harbour", {"--color-primary": "#000000"}, "Second.")
    assert constitution._resolve_brand("harbour")["tokens"] == TOKENS

    brands.write("harbour", {"--color-primary": "#000000"}, "Second.", replace=True)
    assert constitution._resolve_brand("harbour")["tokens"] == {"--color-primary": "#000000"}


@pytest.mark.parametrize("slug", ["", "Harbour", "../escape", "a b", "-lead", "none"])
def test_a_bad_slug_is_refused(tmp_home: Path, slug: str):
    with pytest.raises(ConfigError):
        brands.write(slug, TOKENS, "Prose.")
    assert not paths.brands().exists() or not any(paths.brands().iterdir())


def test_assets_are_copied_into_the_brand(tmp_home: Path, tmp_path: Path):
    logo = support.write(tmp_path / "logo.svg", "<svg/>")

    folder = brands.write("harbour", TOKENS, "Prose.", assets=[logo])

    assert (folder / "assets" / "logo.svg").read_text(encoding="utf-8") == "<svg/>"


def test_list_brands_is_empty_on_an_empty_hub_then_sorted(tmp_home: Path):
    assert brands.list_brands() == []
    brands.write("zeta", TOKENS, "Z.")
    brands.write("alpha", TOKENS, "A.")
    assert brands.list_brands() == ["alpha", "zeta"]


# --- swatch ------------------------------------------------------------------

def test_the_swatch_shows_every_token_escaped_and_self_contained(tmp_home: Path):
    brands.write("harbour", {
        "--color-primary": "#1b365d",
        "--font-body": '"Inter", <script>alert(1)</script>',
    }, "Prose.")

    page = brands.swatch("harbour")

    assert page == paths.swatch("harbour")
    html = page.read_text(encoding="utf-8")
    assert "--color-primary" in html and "#1b365d" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "http://" not in html and "https://" not in html, "the swatch reaches the network"


# --- extractors write nothing ------------------------------------------------

def test_extractors_write_nothing(tmp_home: Path, tmp_path: Path):
    pdf = support.make_pdf(tmp_path / "guide.pdf", ["#1B365D"])
    css = support.write(tmp_path / "site.css", ":root { --a: #fff; }")
    svg = support.write(tmp_path / "logo.svg", '<svg fill="#123456"/>')
    before = support.tree_mtimes(tmp_path)

    brands.from_pdf(pdf)
    brands.from_css(css)
    brands.from_image(svg)

    assert support.tree_mtimes(tmp_path) == before
