"""About it: what she told Taller when the project started, and changing it.

Five cards in her words. Changing one is judged by the same code the interview
uses, and written the way `taller project brief` writes it - carrying her own
rules over - so the page and the terminal cannot disagree.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import project_settings
from taller import discovery, own_rules, paths, scaffold

MACHINE_WORDS = ("slice", "constitution", "profile", "brief.yml", "sha", "commit", "yaml",
                 "what_it_does", "must_never_break", "sensitive_data")


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    return support.new_project()


@pytest.fixture
def client(project):
    return cockpit.create_app(testing=True).test_client()


def read(client, where: str) -> str:
    page = client.get(where).get_data(as_text=True)
    page = re.sub(r"(?s)<(style|script)\b.*?</\1>", " ", page)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def test_the_answers_are_shown_as_she_gave_them(project, client):
    answers = scaffold.load_brief(project)

    page = read(client, "/project/toolshed/about")

    assert "What it does" in page and answers["what_it_does"] in page
    assert "What would be a disaster if it broke" in page and answers["must_never_break"] in page
    assert "What it should never turn into" in page
    assert "What it keeps" in page and "Who uses it, and where" in page


def test_changing_one_answer_rewrites_the_rules_it_feeds(project, client):
    client.post("/project/toolshed/about", follow_redirects=True,
                data={**token(client), "must_never_break": "Knowing who has which tool today."})

    assert scaffold.load_brief(project)["must_never_break"] == "Knowing who has which tool today."
    product = (paths.project_constitution(project) / "product.md").read_text(encoding="utf-8")
    assert "Knowing who has which tool today." in product
    assert "Knowing who has which tool today." in (project / ".taller" / "resolved.json") \
        .read_text(encoding="utf-8")


def test_a_refused_answer_says_why_and_changes_nothing(project, client):
    before = scaffold.load_brief(project)

    answer = client.post("/project/toolshed/about", follow_redirects=True,
                         data={**token(client), "users": "everybody and nobody"})

    assert scaffold.load_brief(project) == before
    page = html.unescape(answer.get_data(as_text=True))
    assert "choose one of the options" in page.lower()


def test_her_own_rules_survive_changing_an_answer_from_the_page(project, client):
    own_rules.add(project, "never", "Show a neighbour's phone number.")

    client.post("/project/toolshed/about", follow_redirects=True,
                data={**token(client), "what_it_is_not": "A shop."})

    assert [rule["text"] for rule in own_rules.read(project)["never"]] == \
        ["Show a neighbour's phone number."]
    assert scaffold.load_brief(project)["what_it_is_not"] == "A shop."


def test_several_answers_on_one_card_are_one_change(project, client):
    before = support.git(project, "rev-list", "--count", "main").strip()

    client.post("/project/toolshed/about", follow_redirects=True,
                data={**token(client), "users": "team", "reach": "a VPN", "phone": "y"})

    answers = scaffold.load_brief(project)
    assert (answers["users"], answers["reach"], answers["phone"]) == ("team", "a VPN", True)
    after = support.git(project, "rev-list", "--count", "main").strip()
    assert int(after) - int(before) <= 2, "one amendment, and its refresh"


def test_money_and_personal_details_are_said_plainly(project, client):
    client.post("/project/toolshed/about", follow_redirects=True,
                data={**token(client), "sensitive_data": "y"})

    page = read(client, "/project/toolshed/about")

    assert "every change touching them is checked twice" in page


def test_the_front_page_links_each_project_to_its_settings(project, client):
    raw = client.get("/").get_data(as_text=True)

    assert 'href="/project/toolshed/about"' in raw


def test_changing_needs_the_token(project, client):
    before = scaffold.load_brief(project)

    answer = client.post("/project/toolshed/about", data={"what_it_is_not": "A shop."})

    assert answer.status_code == 400 and scaffold.load_brief(project) == before


def test_the_settings_pages_name_nothing_from_the_machine(project, client):
    page = read(client, "/project/toolshed/about").lower()

    assert not [word for word in MACHINE_WORDS if word in page]
