"""Look and feel: the brand as colours and type, and making one from a guide.

A brand is shown as swatches named in words and typefaces as sentences set in
them - never as token names. Changing a colour reaches every project using the
brand, and the page says which ones first. A brand guide dropped on the page
becomes a proposal she checks; nothing is written until she saves. Putting a
brand on a project changes the app's own files, so that is asked for as work.
"""

from __future__ import annotations

import html
import re
import types
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import project_settings, runs
from taller import brands, discovery, hub, paths, tickets


@pytest.fixture
def hub_brand(tmp_home: Path, identity, stub_claude, monkeypatch) -> str:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    if not (hub.read_config().get("language") or {}).get("code"):
        hub.update_config({"language": {"code": "en", "ui": "es", "commits": "en"}})
    support.make_brand("harbour")
    hub.commit("a brand")
    return "harbour"


@pytest.fixture
def project(hub_brand) -> Path:
    return support.new_project(brand=hub_brand)


@pytest.fixture
def plain_project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    return support.new_project()


@pytest.fixture
def started(monkeypatch) -> list[list[str]]:
    seen: list[list[str]] = []

    def fake(command, log):
        seen.append(list(command))
        log.write_text("working\n", encoding="utf-8")
        return types.SimpleNamespace(pid=4321, poll=lambda: None)

    monkeypatch.setattr(runs, "_spawn", fake)
    return seen


def client_for() -> object:
    return cockpit.create_app(testing=True).test_client()


def read(client, where: str) -> str:
    page = client.get(where).get_data(as_text=True)
    page = re.sub(r"(?s)<(style|script)\b.*?</\1>", " ", page)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def tokens_of(slug: str) -> dict[str, str]:
    return brands.tokens_in((paths.brands() / slug / "tokens.css").read_text(encoding="utf-8"))


def test_the_brand_is_shown_as_colours_and_type_not_tokens(project):
    client = client_for()

    page = read(client, "/project/toolshed/look")

    assert "Main" in page and "Accent" in page and "#1b365d" in page.lower()
    assert "Inter" in page
    assert "--color-primary" not in page and "--font-body" not in page


def test_changing_a_colour_reaches_every_project_that_uses_it(project):
    client = client_for()

    client.post("/project/toolshed/look/save", follow_redirects=True,
                data={**token(client), "slug": "harbour", "t:--color-primary": "#aa0000",
                      "t:--color-accent": "#c8a45c", "t:--font-body": '"Inter", sans-serif',
                      "prose": "Calm and plain."})

    assert tokens_of("harbour")["--color-primary"] == "#aa0000"
    snapshot = (project / ".taller" / "resolved.json").read_text(encoding="utf-8")
    assert "#aa0000" in snapshot.lower()


def test_a_shared_brand_says_who_else_it_changes(project):
    support.new_project("boathouse", brand="harbour")
    client = client_for()

    page = read(client, "/project/toolshed/look")

    assert "also used by boathouse" in page.lower()


def test_a_project_with_no_brand_says_so(plain_project):
    page = read(client_for(), "/project/toolshed/look")

    assert "doesn't use a brand yet" in page


def test_a_brand_guide_is_read_into_a_proposal_she_confirms(plain_project, tmp_path):
    guide = support.make_pdf(tmp_path / "guide.pdf", ["Primary #0F4C5C", "Accent #E36414"],
                             fonts=("Georgia",))
    client = client_for()

    with guide.open("rb") as handle:
        answer = client.post("/project/toolshed/look/guide", content_type="multipart/form-data",
                             data={**token(client), "guide": (handle, "guide.pdf")})

    page = html.unescape(answer.get_data(as_text=True))
    assert answer.status_code == 200
    assert "#0f4c5c" in page.lower() and "#e36414" in page.lower()
    assert brands.list_brands() == [], "a brand was written before she saved"


def test_saving_a_proposal_makes_the_brand(plain_project):
    client = client_for()

    client.post("/project/toolshed/look/save", follow_redirects=True,
                data={**token(client), "new": "1", "name": "Workshop colours",
                      "t:--color-primary": "#0f4c5c", "t:--color-accent": "#e36414",
                      "prose": "Calm and plain."})

    assert brands.list_brands() == ["workshop-colours"]
    assert tokens_of("workshop-colours")["--color-primary"] == "#0f4c5c"


def test_a_file_that_is_not_a_brand_guide_is_refused_with_a_sentence(plain_project, tmp_path):
    letter = tmp_path / "letter.docx"
    letter.write_bytes(b"PK\x03\x04 not a guide")
    client = client_for()

    with letter.open("rb") as handle:
        answer = client.post("/project/toolshed/look/guide", content_type="multipart/form-data",
                             data={**token(client), "guide": (handle, "letter.docx")},
                             follow_redirects=True)

    page = html.unescape(answer.get_data(as_text=True))
    assert "PDF" in page and "Traceback" not in page
    assert brands.list_brands() == []


def test_a_file_that_is_too_big_is_refused_before_it_is_read(plain_project, tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr(project_settings, "UPLOAD_MAX", 1024)
    big = tmp_path / "huge.pdf"
    big.write_bytes(b"%PDF-1.4\n" + b"0" * 4096)
    read_it: list[Path] = []
    monkeypatch.setattr(project_settings, "_read_guide", lambda path: read_it.append(path))
    client = client_for()

    with big.open("rb") as handle:
        answer = client.post("/project/toolshed/look/guide", content_type="multipart/form-data",
                             data={**token(client), "guide": (handle, "huge.pdf")},
                             follow_redirects=True)

    assert "too big" in html.unescape(answer.get_data(as_text=True)).lower()
    assert read_it == []


def test_nothing_is_kept_of_the_file_itself(plain_project, tmp_path):
    guide = support.make_pdf(tmp_path / "guide.pdf", ["Primary #0F4C5C"])
    client = client_for()

    with guide.open("rb") as handle:
        client.post("/project/toolshed/look/guide", content_type="multipart/form-data",
                    data={**token(client), "guide": (handle, "guide.pdf")})

    kept = paths.run_dir() / "cockpit-uploads"
    assert not kept.exists() or not any(kept.iterdir())


def test_putting_a_brand_on_a_project_is_asked_for_as_work(plain_project, hub_brand, started):
    client = client_for()

    client.post("/project/toolshed/look/use", follow_redirects=True,
                data={**token(client), "slug": "harbour"})

    ticket = tickets.load(plain_project, 1)
    assert "harbour" in tickets._words(plain_project, ticket)
    assert started and started[0][-4:] == ["run", "1", "--path", str(plain_project)]
