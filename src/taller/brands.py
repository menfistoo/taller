"""Brands: propose a palette from a guide, a stylesheet or a logo; write one.

Spec 4.2. A brand is a folder in the hub. Colour and font **values** exist only in
`brands/<slug>/tokens.css`; `brand.md` says which token applies where, by name.

The extractors propose and never decide. A brand guide PDF is preferred when one
exists, because a stylesheet is an implementation that may already have drifted
from the guide. Extraction is deterministic text matching, never inference, and a
PDF with no text layer yields nothing rather than a guess from pixels. The swatch
page is the approval step; `write` is the only writer.
"""

from __future__ import annotations

import html
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import locking, paths
from .errors import ConfigError

Proposal = dict[str, Any]

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# `none` is how a project says it has no brand (spec 4.1); a brand of that name
# would be unreachable.
RESERVED_SLUGS = frozenset({"none"})

# Word-bounded both sides, so `#1B365D` matches and `&#123;` or `#1B365DFF`
# (eight digits: alpha) does not.
_HEX = re.compile(r"(?<![\w&#])#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-zA-Z_])")
# `C 0 M 45 Y 100 K 0` and its variants with `:`/`=`/`%`/commas.
_CMYK_LABELLED = re.compile(
    r"\bC\s*[:=]?\s*(\d{1,3})\s*%?\s*[,/]?\s*"
    r"M\s*[:=]?\s*(\d{1,3})\s*%?\s*[,/]?\s*"
    r"Y\s*[:=]?\s*(\d{1,3})\s*%?\s*[,/]?\s*"
    r"K\s*[:=]?\s*(\d{1,3})\s*%?"
)
# `CMYK 0/45/100/0` and `CMYK: 0, 45, 100, 0`.
_CMYK_LIST = re.compile(
    r"\bCMYK\s*[:=]?\s*(\d{1,3})\s*%?\s*[,/ ]\s*(\d{1,3})\s*%?\s*[,/ ]\s*"
    r"(\d{1,3})\s*%?\s*[,/ ]\s*(\d{1,3})\s*%?"
)
_FONT_LABEL = re.compile(
    r"^\s*(?:font|fonts|typeface|typography|primary font|secondary font)\s*[:\-–]\s*(.+?)\s*$",
    re.IGNORECASE,
)
_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
# A PDF viewer's built-in fonts: a document using them says nothing about a brand.
_STANDARD_FONTS = frozenset({
    "Helvetica", "Times", "Times-Roman", "Courier", "Symbol", "ZapfDingbats",
    "Arial", "TimesNewRoman", "CourierNew",
})
_SVG_COLOUR = re.compile(
    r"(?:fill|stroke|stop-color)\s*[=:]\s*[\"']?\s*(#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})\b"
)
_CSS_TOKEN = re.compile(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;{}]+?)\s*(?:;|(?=}))")
_ROOT_BLOCK = re.compile(r":root\s*\{([^}]*)\}", re.DOTALL)

# Colours closer than this (Euclidean, RGB) are one colour in a raster logo:
# antialiasing produces dozens of near-identical shades along every edge.
_RASTER_MERGE_DISTANCE = 24
_RASTER_MAX_SIDE = 256
_MAX_COLOURS = 8


# --- normalising -------------------------------------------------------------

def normalise_hex(value: str) -> str:
    """`#ABC` -> `#aabbcc`; `#1B365D` -> `#1b365d`. The one spelling compared."""
    digits = value.lstrip("#").lower()
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return f"#{digits}"


def cmyk_to_hex(c: int, m: int, y: int, k: int) -> str:
    """Naive CMYK -> RGB. A proposal, not a colour-managed conversion."""
    def channel(ink: int) -> int:
        return int(255 * (1 - ink / 100) * (1 - k / 100) + 0.5)
    return "#{:02x}{:02x}{:02x}".format(channel(c), channel(m), channel(y))


def _ranked(hits: Iterable[tuple[int, str]]) -> list[dict[str, Any]]:
    """(position, hex) pairs -> colours by count desc, then first appearance."""
    counts: Counter[str] = Counter()
    first: dict[str, int] = {}
    for position, value in hits:
        counts[value] += 1
        first.setdefault(value, position)
    ordered = sorted(counts, key=lambda value: (-counts[value], first[value]))
    return [{"hex": value, "count": counts[value], "first": first[value]}
            for value in ordered]


def _proposal(source: str, colours: list, fonts: list, notes: list) -> Proposal:
    return {"source": source, "colours": colours, "fonts": fonts, "notes": notes}


# --- from_pdf ----------------------------------------------------------------

def from_pdf(path: Path | str) -> Proposal:
    """Colours and fonts a brand guide declares, ranked (spec 4.2)."""
    import pypdf                         # local: only this path needs it

    path = Path(path)
    try:
        reader = pypdf.PdfReader(str(path))
        pages = list(reader.pages)
        text = "\n".join(page.extract_text() or "" for page in pages)
    except (pypdf.errors.PdfReadError, ValueError, OSError) as exc:
        raise ConfigError(f"{path} could not be read as a PDF: {exc}") from exc

    notes: list[str] = []
    if not text.strip():
        notes.append(
            "No text layer - this looks like a scanned PDF. Nothing was extracted; "
            "colours are never guessed from rendered pixels."
        )

    fonts = _labelled_fonts(text) + _embedded_fonts(pages)
    return _proposal("pdf", _ranked(_colour_hits(text)), _unique(fonts), notes)


def _colour_hits(text: str) -> list[tuple[int, str]]:
    hits = [(m.start(), normalise_hex(m.group(0))) for m in _HEX.finditer(text)]
    for pattern in (_CMYK_LABELLED, _CMYK_LIST):
        for match in pattern.finditer(text):
            inks = [int(group) for group in match.groups()]
            if all(0 <= ink <= 100 for ink in inks):
                hits.append((match.start(), cmyk_to_hex(*inks)))
    return sorted(hits)


def _labelled_fonts(text: str) -> list[str]:
    fonts = []
    for line in text.splitlines():
        match = _FONT_LABEL.match(line)
        if match:
            name = re.split(r"[,(;]", match.group(1))[0].strip().strip("\"'")
            if name:
                fonts.append(name)
    return fonts


def _embedded_fonts(pages: list) -> list[str]:
    fonts = []
    for page in pages:
        try:
            resources = page.get("/Resources") or {}
            font_dict = resources.get_object().get("/Font") or {}
            entries = font_dict.get_object().values()
        except (AttributeError, KeyError):
            continue
        for ref in entries:
            base = str(ref.get_object().get("/BaseFont", "")).lstrip("/")
            family = re.split(r"[-,]", _SUBSET_PREFIX.sub("", base))[0]
            if family and family not in _STANDARD_FONTS:
                fonts.append(family)
    return fonts


def _unique(items: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
    return list(seen)


# --- from_css ----------------------------------------------------------------

def from_css(path: Path | str) -> dict[str, str]:
    """Every `--*` custom property in a stylesheet's `:root` blocks, in order.

    Last declaration wins, as in the browser. This is also adoption's lift
    (spec 4.2.1 step 1), so it reads the same blocks a browser would apply.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return tokens_in(text)


def tokens_in(css: str) -> dict[str, str]:
    """`--*` properties from `:root` blocks of CSS text. Shared with discovery."""
    tokens: dict[str, str] = {}
    for block in _ROOT_BLOCK.findall(_strip_comments(css)):
        for name, value in _CSS_TOKEN.findall(block):
            tokens[name] = " ".join(value.split())
    return tokens


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


# --- from_image --------------------------------------------------------------

def from_image(path: Path | str) -> Proposal:
    """Dominant colours of a logo. SVG by its literal colours; raster by area."""
    path = Path(path)
    if path.suffix.lower() == ".svg":
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = [(m.start(), normalise_hex(m.group(1))) for m in _SVG_COLOUR.finditer(text)]
        return _proposal("image", _ranked(hits)[:_MAX_COLOURS], [], [])
    return _proposal("image", _raster_colours(path), [], [])


def _raster_colours(path: Path) -> list[dict[str, Any]]:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
    except (UnidentifiedImageError, OSError) as exc:
        raise ConfigError(f"{path} could not be read as an image: {exc}") from exc
    # NEAREST, so downscaling cannot invent blended colours the logo never had.
    image.thumbnail((_RASTER_MAX_SIDE, _RASTER_MAX_SIDE), Image.NEAREST)

    counts = image.getcolors(maxcolors=image.width * image.height) or []
    opaque = sorted(((n, rgba[:3]) for n, rgba in counts if rgba[3] >= 128),
                    key=lambda pair: (-pair[0], pair[1]))

    clusters: list[list[Any]] = []            # [representative rgb, pixel count]
    for n, rgb in opaque:
        for cluster in clusters:
            if _distance(cluster[0], rgb) <= _RASTER_MERGE_DISTANCE:
                cluster[1] += n
                break
        else:
            clusters.append([rgb, n])
    clusters.sort(key=lambda cluster: -cluster[1])
    return [
        {"hex": "#{:02x}{:02x}{:02x}".format(*rgb), "count": n, "first": index}
        for index, (rgb, n) in enumerate(clusters[:_MAX_COLOURS])
    ]


def _distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


# --- proposing tokens --------------------------------------------------------

def propose_tokens(proposal: Proposal) -> dict[str, str]:
    """Name a proposal's values so the swatch page can show them.

    Names are a starting point; the owner renames on the swatch step.
    """
    tokens: dict[str, str] = {}
    colour_names = ["--color-primary", "--color-accent"]
    for index, colour in enumerate(proposal.get("colours", [])):
        name = colour_names[index] if index < len(colour_names) else f"--color-{index + 1}"
        tokens[name] = colour["hex"]
    for name, font in zip(["--font-body", "--font-heading"], proposal.get("fonts", [])):
        tokens[name] = f'"{font}", sans-serif'
    return tokens


# --- the hub -----------------------------------------------------------------

def list_brands() -> list[str]:
    """Every brand the hub holds. Empty on a fresh hub (spec 4.0)."""
    root = paths.brands()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "tokens.css").is_file())


def validate_slug(slug: str) -> str:
    if not isinstance(slug, str) or not SLUG.match(slug) or slug in RESERVED_SLUGS:
        raise ConfigError(
            f"{slug!r} is not a usable brand name: lowercase letters, digits and "
            f"hyphens, starting with a letter or digit"
            + (", and not `none`, which means no brand." if slug in RESERVED_SLUGS else ".")
        )
    return slug


def write(slug: str, tokens: Mapping[str, str], prose: str, *,
          assets: Iterable[Path | str] = (), replace: bool = False) -> Path:
    """Write a brand into the hub: `tokens.css`, `brand.md`, `assets/`."""
    validate_slug(slug)
    css = render_tokens_css(tokens)
    brand_md = render_brand_md(prose)
    asset_paths = [Path(asset) for asset in assets]
    for asset in asset_paths:
        if not asset.is_file():
            raise ConfigError(f"Brand asset {asset} does not exist.")

    folder = paths.brands() / slug
    with locking.hub_lock():
        if (folder / "tokens.css").exists() and not replace:
            raise ConfigError(
                f"Brand {slug!r} already exists at {folder}. A brand is the owner's "
                f"once written; edit it there, or replace it explicitly."
            )
        folder.mkdir(parents=True, exist_ok=True)
        locking.atomic_write(folder / "tokens.css", css.encode("utf-8"))
        locking.atomic_write(folder / "brand.md", brand_md.encode("utf-8"))
        for asset in asset_paths:
            (folder / "assets").mkdir(exist_ok=True)
            shutil.copyfile(asset, folder / "assets" / asset.name)
    return folder


def render_tokens_css(tokens: Mapping[str, str]) -> str:
    """One `:root` block, LF. Refuses a value that would break out of it."""
    if not tokens:
        raise ConfigError("A brand needs at least one token.")
    lines = [
        "/* Brand tokens: the only place colour and font values are defined. */",
        ":root {",
    ]
    for name, value in tokens.items():
        if not re.fullmatch(r"--[A-Za-z0-9_-]+", name):
            raise ConfigError(f"{name!r} is not a CSS custom property name.")
        value = str(value).strip()
        if not value or re.search(r"[;{}\n\r]", value):
            raise ConfigError(f"The value of {name} ({value!r}) is not a single CSS value.")
        lines.append(f"  {name}: {value};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_brand_md(prose: str) -> str:
    """`brand.md`: its first line is the `> ` summary the index collects (3.1).

    Later lines that would read as a second summary are escaped: the index
    collects every `> ` line, and a brand is shared by every project using it.
    """
    lines = [line.rstrip() for line in str(prose).strip().splitlines()]
    if not lines or not lines[0]:
        raise ConfigError("A brand needs at least one line saying what it is for.")
    head = lines[0][2:] if lines[0].startswith("> ") else lines[0]
    body = [f"\\{line}" if line.startswith("> ") else line for line in lines[1:]]
    return "\n".join([f"> {head}", "", *body]).rstrip("\n") + "\n"


# --- the swatch --------------------------------------------------------------

def swatch(slug: str) -> Path:
    """Render the brand's review page to `~/.taller-run/swatches/<slug>.html`.

    Self-contained - no network, no external font - and every value escaped: a
    token value is owner input rendered into HTML.
    """
    folder = paths.brands() / validate_slug(slug)
    tokens_path = folder / "tokens.css"
    if not tokens_path.is_file():
        raise ConfigError(f"Brand {slug!r} has no tokens.css at {tokens_path}.")
    tokens = tokens_in(tokens_path.read_text(encoding="utf-8"))
    prose_path = folder / "brand.md"
    prose = prose_path.read_text(encoding="utf-8") if prose_path.is_file() else ""

    page = paths.swatch(slug)
    page.parent.mkdir(parents=True, exist_ok=True)
    locking.atomic_write(page, render_swatch(slug, tokens, prose).encode("utf-8"))
    return page


def render_swatch(slug: str, tokens: Mapping[str, str], prose: str) -> str:
    esc = html.escape
    colours, fonts, other = [], [], []
    for name, value in tokens.items():
        if _looks_like_colour(value):
            colours.append(
                f'<figure><div class="chip" style="background:{esc(value)}"></div>'
                f"<figcaption><code>{esc(name)}</code><br>{esc(value)}</figcaption></figure>"
            )
        elif name.startswith("--font"):
            fonts.append(
                f'<p style="font-family:{esc(value)}"><code>{esc(name)}</code> '
                f"The quick brown fox jumps over the lazy dog. 0123456789</p>"
            )
        else:
            other.append(f"<tr><td><code>{esc(name)}</code></td><td>{esc(value)}</td></tr>")

    return "\n".join([
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Brand {esc(slug)}</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:2rem;max-width:60rem;color:#222}",
        "figure{display:inline-block;margin:0 1rem 1rem 0;text-align:center}",
        ".chip{width:7rem;height:5rem;border:1px solid #ccc;border-radius:6px}",
        "td{padding:.2rem 1rem .2rem 0}",
        "</style></head><body>",
        f"<h1>Brand <code>{esc(slug)}</code></h1>",
        f"<pre>{esc(prose)}</pre>",
        "<h2>Colours</h2>", *colours,
        "<h2>Typography</h2>", *fonts,
        *(["<h2>Other tokens</h2>", "<table>", *other, "</table>"] if other else []),
        "</body></html>",
        "",
    ])


def _looks_like_colour(value: str) -> bool:
    return bool(re.fullmatch(r"#[0-9a-fA-F]{3,8}|(?:rgb|rgba|hsl|hsla)\([^)]*\)", value.strip()))
