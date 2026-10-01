"""Its rules: what the project must always and never do, in her words.

Her rules, each with why and when; the exceptions she has allowed, with when
they run out; and the rules that come with Taller, one plain line each - shown so
she knows they are there, not offered for editing.
"""

from __future__ import annotations

import html
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import project_settings, words
from taller import catalogue, discovery, own_rules, paths

MACHINE_WORDS = ("override", "slice", "constitution", "module", "size.", "brand.", "tests.",
                 "scope", "sha", "commit", "stack/", "ux/", "security/")


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


def an_exception(project: Path, until: date) -> None:
    support.write(paths.project_constitution(project) / "overrides.md",
                  "---\noverrides:\n  - rule: size.file-too-long\n"
                  "    scope: \"loans/ledger.py\"\n"
                  "    reason: \"It is being split, one piece at a time.\"\n"
                  f"    until: {until.isoformat()}\n---\n")
    support.git(project, "add", "--all")
    support.git(project, "commit", "--quiet", "-m", "docs: an exception")


def test_her_rules_are_listed_under_always_and_never(project, client):
    own_rules.add(project, "always", "Show amounts with two decimals.", "The accountant asks.")
    own_rules.add(project, "never", "Show a neighbour's phone number.")

    page = read(client, "/project/toolshed/rules")

    assert "It must always" in page and "Show amounts with two decimals." in page
    assert "The accountant asks." in page
    assert "It must never" in page and "Show a neighbour's phone number." in page


def test_adding_a_rule_from_the_page_records_it_with_its_reason(project, client):
    client.post("/project/toolshed/rules/add", follow_redirects=True,
                data={**token(client), "kind": "always", "text": "Keep the loans list sorted.",
                      "why": "It is easier to read."})

    rule = own_rules.read(project)["always"][0]
    assert (rule["text"], rule["why"]) == ("Keep the loans list sorted.", "It is easier to read.")


def test_removing_a_rule_asks_why(project, client):
    own_rules.add(project, "always", "Keep the loans list sorted.")

    refused = client.post("/project/toolshed/rules/remove", follow_redirects=True,
                          data={**token(client), "kind": "always", "index": "0", "why": ""})
    assert own_rules.read(project)["always"], "removed without a reason"
    assert "reason" in html.unescape(refused.get_data(as_text=True)).lower()

    client.post("/project/toolshed/rules/remove", follow_redirects=True,
                data={**token(client), "kind": "always", "index": "0",
                      "why": "Sorting is done elsewhere now."})
    assert own_rules.read(project)["always"] == []


def test_an_exception_says_until_when_in_words(project, client):
    an_exception(project, date(2026, 12, 31))

    page = read(client, "/project/toolshed/rules")

    assert "Exceptions you've allowed" in page
    assert "One file is getting long" in page and "It is being split" in page
    assert "Until 31 December 2026" in page
    assert "size.file-too-long" not in page and "loans/ledger.py" not in page


def test_an_exception_that_has_run_out_says_so(project, client):
    an_exception(project, date.today() - timedelta(days=3))

    page = read(client, "/project/toolshed/rules")

    assert "ran out" in page.lower() and "applies again" in page.lower()


def test_every_rule_file_taller_ships_has_a_plain_line():
    shipped = {path.relative_to(paths.catalogue() / "modules").with_suffix("").as_posix()
               for path in (paths.catalogue() / "modules").rglob("*.md")}

    assert shipped <= set(words.PRACTICE), shipped - set(words.PRACTICE)


def test_taller_rules_are_shown_but_not_offered_for_editing(project, client):
    raw = client.get("/project/toolshed/rules").get_data(as_text=True)
    page = read(client, "/project/toolshed/rules")

    assert "Rules that come with Taller" in page
    assert "You don't need to look after these." in page
    assert words.PRACTICE["never"] in page
    assert raw.count('action="/project/toolshed/rules/add"') == 2, "one add box per list, no more"


def test_a_rule_file_with_no_plain_line_shows_its_own_summary_not_its_name(project, monkeypatch):
    monkeypatch.setattr(words, "PRACTICE", {})

    found = project_settings.rules("toolshed")

    assert found["practice"] and not [line for line in found["practice"] if "/" in line]


def test_the_page_names_nothing_from_the_machine(project, client):
    an_exception(project, date(2026, 12, 31))
    own_rules.add(project, "always", "Show amounts with two decimals.")

    page = read(client, "/project/toolshed/rules").lower()

    assert not [word for word in MACHINE_WORDS if word in page]


def test_what_the_page_says_after_a_change_names_nothing_from_the_machine(project, client):
    added = client.post("/project/toolshed/rules/add", follow_redirects=True,
                        data={**token(client), "kind": "always",
                              "text": "Keep the loans list sorted."})
    removed = client.post("/project/toolshed/rules/remove", follow_redirects=True,
                          data={**token(client), "kind": "always", "index": "0",
                                "why": "Sorting is done elsewhere now."})

    for answer in (added, removed):
        page = html.unescape(answer.get_data(as_text=True)).lower()
        assert "saved. taller checks every change against it from now on." in page
        assert not [word for word in (*MACHINE_WORDS, "sync")
                    if re.search(rf"\b{re.escape(word)}", page)]


def test_what_it_should_never_turn_into_is_shown_among_the_never_rules(project, client):
    """Her answer on About it is a never-rule too: shown in the list, changed there."""
    from taller import scaffold

    what_not = scaffold.load_brief(project)["what_it_is_not"]

    page = read(client, "/project/toolshed/rules")

    assert what_not in page and "From About it" in page
