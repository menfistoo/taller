"""Written text - plans, summaries - shown as text rather than as markup.

Plans and summaries arrive as Markdown, and on a page `## What it delivers` and
`**new**` are the machine showing through. This is deliberately tiny rather than
a Markdown library: headings, paragraphs, bullet lists, bold and inline code,
and nothing else. Everything is escaped first, so whatever a model wrote can only
ever become those few tags - never a link, an image or a script.
"""

from __future__ import annotations

import re

from markupsafe import Markup, escape

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_HEADING = re.compile(r"^#{1,6}\s+(.*)$")
_BULLET = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*)$")


def render(text: str | None) -> Markup:
    """Markdown-ish text -> a few safe tags."""
    if not text:
        return Markup("")
    out: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if paragraph:
            out.append(f"<p>{' '.join(paragraph)}</p>")
            paragraph.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>")
            items.clear()

    for raw in str(text).replace("\r\n", "\n").split("\n"):
        line = _inline(str(escape(raw.rstrip())))
        heading = _HEADING.match(raw.strip())
        bullet = _BULLET.match(raw)
        if not raw.strip():
            flush()
        elif heading:
            flush()
            out.append(f"<h3>{_inline(str(escape(heading.group(1))))}</h3>")
        elif bullet:
            if paragraph:
                flush()
            items.append(_inline(str(escape(bullet.group(1)))))
        else:
            if items:
                flush()
            paragraph.append(line.strip())
    flush()
    return Markup("\n".join(out))


def _inline(escaped: str) -> str:
    """Bold and code, on text that is already escaped."""
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    return _CODE.sub(r"<code>\1</code>", escaped)
