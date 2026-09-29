"""`taller brand new`: a brand, guided, reviewed as a swatch before it is written.

Spec 4.2. Starting points in order of authority: a brand guide PDF, a
stylesheet, a logo, then scratch. Whatever the start, the owner sees named
tokens, can change any of them, writes one line of intent, and approves the
swatch page. `brands.write` runs only after that approval.
"""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Any

from .. import brands, generated, hub, locking, paths
from ..errors import ConfigError
from ..onboarding import Question, ask
from ..prompter import Prompter

STARTS = (
    ("pdf", "a brand guide PDF (the most reliable source)"),
    ("css", "an existing stylesheet"),
    ("image", "a logo image"),
    ("scratch", "from scratch"),
)

# Asked for a scratch brand, with Bootstrap's own values as the defaults for
# everything a brand usually does not care about.
SCRATCH = (
    ("--color-primary", "Primary colour, as #rrggbb", None),
    ("--color-accent", "Accent colour", None),
    ("--color-success", "Success colour", "#198754"),
    ("--color-warning", "Warning colour", "#ffc107"),
    ("--color-danger", "Danger colour", "#dc3545"),
    ("--color-surface", "Background colour", "#ffffff"),
    ("--color-text", "Text colour", "#212529"),
    ("--font-body", "Body font", "system-ui, sans-serif"),
    ("--font-heading", "Heading font", "system-ui, sans-serif"),
    ("--space-unit", "Spacing unit", "0.5rem"),
)


def open_in_browser(page: Path) -> None:
    """A seam, so tests never launch a browser."""
    webbrowser.open(page.resolve().as_uri())


def create(prompter: Prompter, *, slug: str | None = None,
           open_page: bool = True) -> str | None:
    """Run the wizard. Returns the new brand's slug, or None if cancelled."""
    slug = _slug(prompter, slug)
    tokens, assets = _start(prompter)
    saved = _review_and_save(prompter, slug, tokens, assets=assets, open_page=open_page)
    if saved:
        hub.commit(f"brand: add {slug}")
        prompter.say(f"Saved {slug} to your hub.")
        return slug
    return None


def _review_and_save(prompter: Prompter, slug: str, tokens: dict[str, str], *,
                     assets: list[Path], open_page: bool, intent: str | None = None,
                     replace: bool = False) -> bool:
    """Tokens, intent, swatch, approve. Writes only on approval."""
    while True:
        tokens = _review(prompter, tokens)
        intent = ask(prompter, Question(
            "brand.intent", "intent", 0,
            "In one line: what should this brand feel like, and what is each colour for?",
            "text"), default=intent)
        page = paths.swatch(slug)
        locking.atomic_write_text(page, brands.render_swatch(slug, tokens, f"> {intent}"))
        prompter.say(f"The swatch page is at {page}")
        if open_page:
            open_in_browser(page)

        decision = ask(prompter, Question(
            "brand.approve", "approve", 0, f"Save the brand {slug!r}?", "choice",
            choices=(("save", "save it"), ("edit", "change the tokens"),
                     ("cancel", "cancel, writing nothing"))))
        if decision == "cancel":
            prompter.say("Nothing was written.")
            return False
        if decision == "save":
            brands.write(slug, tokens, intent, assets=assets, replace=replace)
            return True


def edit(args: Any, prompter: Prompter) -> int:
    """`taller brand edit`: change a brand, then refresh every project using it (4.6)."""
    slug = getattr(args, "slug", None)
    if slug is None:
        existing = brands.list_brands()
        if not existing:
            raise ConfigError("The hub has no brands yet. `taller brand new` creates one.")
        slug = ask(prompter, Question("brand.pick", "brand", 0, "Which brand?", "choice",
                                      choices=tuple((s, s) for s in existing)))
    folder = paths.brands() / brands.validate_slug(slug)
    if not (folder / "tokens.css").is_file():
        raise ConfigError(f"The hub has no brand {slug!r}.")
    tokens = brands.tokens_in((folder / "tokens.css").read_text(encoding="utf-8"))
    prose = (folder / "brand.md").read_text(encoding="utf-8") if (folder / "brand.md").is_file() else ""
    intent = next((line[2:] for line in prose.splitlines() if line.startswith("> ")), None)

    if not _review_and_save(prompter, slug, tokens, assets=[], intent=intent, replace=True,
                            open_page=not getattr(args, "no_open", False)):
        return 1
    if not hub.commit(f"brand: amend {slug}"):
        prompter.say("Nothing changed.")
        return 0
    touched = generated.refresh_affected(brand=slug, message=f"taller: resolve after brand {slug}")
    prompter.say(f"Saved {slug}. " + (
        "Refreshed: " + ", ".join(f"{name} ({sync})" for name, sync in touched)
        if touched else "No adopted project uses it yet."))
    return 0


def _slug(prompter: Prompter, given: str | None) -> str:
    candidate = given
    while True:
        if candidate is None:
            candidate = prompter.ask(
                "brand.slug",
                "  A short name for the brand: lowercase letters, digits and hyphens",
            ).strip()
        try:
            brands.validate_slug(candidate)
        except ConfigError as exc:
            prompter.say(f"  {exc}")
            candidate = None
            continue
        if candidate in brands.list_brands():
            prompter.say(f"  The hub already has a brand called {candidate!r}.")
            candidate = None
            continue
        return candidate


def _start(prompter: Prompter) -> tuple[dict[str, str], list[Path]]:
    while True:
        start = ask(prompter, Question("brand.start", "start", 0, "Start from", "choice",
                                       choices=STARTS))
        if start == "scratch":
            return _scratch(prompter), []
        path = _existing_file(prompter, f"brand.{start}", {
            "pdf": "Path to the brand guide PDF",
            "css": "Path to the stylesheet",
            "image": "Path to the logo (PNG, JPG or SVG)",
        }[start])
        try:
            if start == "css":
                tokens = brands.from_css(path)
                notes: list[str] = []
            else:
                proposal = (brands.from_pdf if start == "pdf" else brands.from_image)(path)
                tokens, notes = brands.propose_tokens(proposal), proposal["notes"]
        except ConfigError as exc:
            prompter.say(f"  {exc}")
            continue
        for note in notes:
            prompter.say(f"  {note}")
        if tokens:
            return tokens, [path] if start == "image" else []
        prompter.say("  Nothing usable was found there. Choose another starting point.")


def _existing_file(prompter: Prompter, qid: str, text: str) -> Path:
    while True:
        raw = prompter.ask(qid, f"  {text}").strip().strip('"').strip("'")
        path = Path(raw).expanduser()
        if raw and path.is_file():
            return path
        prompter.say(f"  There is no file at {raw!r}.")


def _scratch(prompter: Prompter) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for name, text, default in SCRATCH:
        tokens[name] = _value(prompter, f"brand.scratch.{name[2:]}", name, text, default)
    return tokens


def _value(prompter: Prompter, qid: str, name: str, text: str, default: Any) -> str:
    prompt = f"  {text}" + (f"\n     [{default}]" if default else "")
    while True:
        raw = prompter.ask(qid, prompt).strip() or (default or "")
        try:
            brands.render_tokens_css({name: raw})
        except ConfigError as exc:
            prompter.say(f"  {exc}")
            continue
        if name.startswith("--color") and not brands._looks_like_colour(raw):
            prompter.say("  A colour is written like #1b365d.")
            continue
        return raw


def _review(prompter: Prompter, tokens: dict[str, str]) -> dict[str, str]:
    """Show the tokens; change, drop or add until the owner accepts them."""
    tokens = dict(tokens)
    while True:
        prompter.say("\n".join(["  Tokens:"] + [
            f"     {n}) {name}: {value}" for n, (name, value) in enumerate(tokens.items(), 1)
        ]))
        raw = prompter.ask(
            "brand.tokens",
            "  Enter to accept · a number to change or drop that token · + to add one",
        ).strip()
        if not raw:
            if tokens:
                return tokens
            prompter.say("  A brand needs at least one token.")
            continue
        if raw == "+":
            name = _name(prompter, "")
            tokens[name] = _value(prompter, "brand.token.value", name, f"Value of {name}", None)
            continue
        if raw.isdigit() and 1 <= int(raw) <= len(tokens):
            old = list(tokens)[int(raw) - 1]
            name = _name(prompter, old)
            if name == "-":
                del tokens[old]
                continue
            value = _value(prompter, "brand.token.value", name, f"Value of {name}",
                           tokens[old])
            # Rebuilt rather than popped, so the edited token keeps its place.
            tokens = {(name if key == old else key): (value if key == old else val)
                      for key, val in tokens.items()}
            continue
        prompter.say(f"  Please press Enter, + or a number from 1 to {len(tokens)}.")


def _name(prompter: Prompter, current: str) -> str:
    while True:
        raw = prompter.ask(
            "brand.token.name",
            f"  Token name, starting with -- (- to drop it)"
            + (f"\n     [{current}]" if current else ""),
        ).strip() or current
        if raw == "-" and current:
            return raw
        try:
            brands.render_tokens_css({raw: "x"})
            return raw
        except ConfigError as exc:
            prompter.say(f"  {exc}")


def run(args: Any, prompter: Prompter) -> int:
    slug = create(prompter, slug=getattr(args, "slug", None),
                  open_page=not getattr(args, "no_open", False))
    return 0 if slug else 1
