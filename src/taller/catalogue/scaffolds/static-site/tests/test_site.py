"""Every local file the page references exists."""

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = []
        self.lang = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "html":
            self.lang = attrs.get("lang")
        for key in ("href", "src"):
            value = attrs.get(key)
            if value and "://" not in value:
                self.found.append(value)


def test_the_page_declares_its_language_and_its_files_exist():
    parser = References()
    parser.feed((ROOT / "index.html").read_text(encoding="utf-8"))

    assert parser.lang
    missing = [ref for ref in parser.found if not (ROOT / ref).is_file()]
    assert missing == []
