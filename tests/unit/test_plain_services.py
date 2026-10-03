"""Connected services (phase G2, Task 7): everything Claude is connected to, and
what Taller's work on each project may use.

Three groups, in words; for the chosen project, Not used · May look · May look and
add. Services that need signing in, or are not working, fold away. A service of
her Claude account is added and signed in on claude.ai - Taller never handles
that sign-in. Any other comes from the public catalogue, makers she would know
first, and is added only after a page that names its maker and says what adding
it means.
"""

from __future__ import annotations

import html
import re
import subprocess
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import words
from taller import connections, discovery

LISTING = """claude.ai Google Drive: https://drive.example.test/mcp - \u2714 Connected
claude.ai Gmail: https://mail.example.test/mcp - \u2714 Connected
claude.ai Cloud Platform: https://cloud.example.test/mcp - ! Needs authentication
plugin:notes:notes-search: node C:/plugins/notes/server.js - \u2714 Connected
plugin:viewer:pdf: npx -y pdf-server --stdio - \u2718 Failed to connect \u2014 closed
plugin:team:gmail:  (HTTP) - - Not configured
weather: npx -y weather-server - \u2714 Connected
"""
CATALOGUE = {"servers": [
    {"server": {"name": "io.github.someone/open-bank-data", "title": "Open Bank Data",
                "description": "Bank rates.",
                "remotes": [{"type": "streamable-http", "url": "https://bank.example.test/mcp"}]}},
    {"server": {"name": "com.stripe/mcp", "title": "Stripe", "description": "Payments.",
                "remotes": [{"type": "streamable-http", "url": "https://stripe.example.test/mcp"}]}},
]}



@pytest.fixture(autouse=True)
def work_use_ready(monkeypatch):
    """What is under the switch (connections.WORK_USE_READY), switched on."""
    monkeypatch.setattr(connections, "WORK_USE_READY", True)

@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    monkeypatch.setattr(connections, "_run_list",
                        lambda: subprocess.CompletedProcess(["claude"], 0, LISTING, ""))
    monkeypatch.setattr(connections, "_learn_run",
                        lambda prefix, server: [f"mcp__{prefix}__search_files"])
    monkeypatch.setattr(connections, "_fetch_catalogue", lambda query: CATALOGUE)
    connections.forget()
    return support.new_project()


@pytest.fixture
def client(project):
    return cockpit.create_app(testing=True).test_client()


@pytest.fixture
def added(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake(argv):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "Added", "")

    monkeypatch.setattr(connections, "_run_add", fake)
    return calls


def read(client, where: str = "/services") -> str:
    page = client.get(where).get_data(as_text=True)
    page = re.sub(r"(?s)<(style|script)\b.*?</\1>", " ", page)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def test_services_are_listed_in_three_groups_in_words(project, client):
    page = read(client)

    assert page.index("Through your Claude account") < page.index("Google Drive")
    assert page.index("Came with your plugins") < page.index("notes-search")
    assert page.index("Added by you") < page.index("weather")
    assert "Connected" in page and "Not used May look May look and add" in page


def test_what_needs_signing_in_or_is_broken_folds_away(project, client):
    page = read(client)

    assert "Cloud Platform — needs you to sign in" in page
    assert words.SERVICES["more"].format(count=1) in page          # the broken pdf


def test_a_repeat_brought_by_a_plugin_is_not_listed_twice(project, client):
    from cockpit import services

    listed = [item["name"].lower() for group in services.page()["groups"]
              for item in [*group["shown"], *group["folded"]]]

    assert listed.count("gmail") == 1


def test_choosing_a_level_writes_the_project(project, client):
    client.post("/services/level", follow_redirects=True,
                data={**token(client), "project": "toolshed", "service": "google_drive",
                      "level": "look"})

    assert connections.allowed(project) == {"google_drive": "look"}
    assert "May look" in read(client, "/services?project=toolshed")


def test_turning_a_service_on_says_it_asks_claude_once(project, client):
    assert words.SERVICES["learn_note"] in read(client)


def test_a_service_that_cannot_be_reached_says_so(project, client, monkeypatch):
    monkeypatch.setattr(connections, "_learn_run", lambda prefix, server: None)

    answer = client.post("/services/level", follow_redirects=True,
                         data={**token(client), "project": "toolshed",
                               "service": "google_drive", "level": "look"})

    assert connections.LEARN_FAILED in html.unescape(answer.get_data(as_text=True))
    assert connections.allowed(project) == {}


def test_adding_an_account_service_sends_her_to_claude_ai(project, client):
    raw = client.get("/services").get_data(as_text=True)

    assert 'href="https://claude.ai/settings/connectors"' in raw
    assert words.SERVICES["account_add"] in html.unescape(raw)


def test_known_makers_come_first_and_the_rest_are_marked(project, client):
    page = read(client, "/services/search?q=bank")

    assert page.index("Stripe") < page.index("Open Bank Data")
    assert "by Stripe" in page
    assert words.SERVICES["others"] in page
    assert page.index(words.SERVICES["others"]) < page.index("Open Bank Data")


def test_nothing_is_added_without_confirming(project, client, added):
    first = client.post("/services/add", follow_redirects=True,
                        data={**token(client), "name": "com.stripe/mcp"})

    assert added == [], "the first press only asks"
    assert "It will be able to act inside Taller's work on the projects you allow" in \
        html.unescape(first.get_data(as_text=True))

    client.post("/services/add", follow_redirects=True,
                data={**token(client), "name": "com.stripe/mcp", "confirmed": "1"})

    assert len(added) == 1
    assert added[0][-2:] == ["stripe", "https://stripe.example.test/mcp"]
    assert "--scope" in added[0] and "user" in added[0]


def test_only_what_the_catalogue_says_is_added(project, client, added):
    client.post("/services/add", follow_redirects=True,
                data={**token(client), "name": "com.stripe/mcp", "confirmed": "1",
                      "url": "https://elsewhere.example.test/mcp"})

    assert "https://elsewhere.example.test/mcp" not in added[0]


def test_a_search_that_fails_is_one_sentence(project, client, monkeypatch):
    def broken(query):
        raise OSError("no network")

    monkeypatch.setattr(connections, "_fetch_catalogue", broken)

    assert words.SERVICES["search_failed"] in read(client, "/services/search?q=bank")


def test_the_page_names_nothing_from_the_machine(project, client):
    page = read(client).lower()

    assert "mcp" not in page and "http" not in page and "google_drive" not in page
    assert "plugin:" not in page and "npx" not in page


def test_every_plain_page_links_here(project, client):
    assert 'href="/services"' in client.get("/").get_data(as_text=True)


def test_a_slow_catalogue_is_asked_twice(project, client, monkeypatch):
    """Measured: the catalogue's first answer can take longer than its timeout."""
    tries: list[str] = []

    def slow_once(query):
        tries.append(query)
        if len(tries) == 1:
            raise TimeoutError("The read operation timed out")
        return CATALOGUE

    monkeypatch.setattr(connections, "_fetch_catalogue", slow_once)

    assert "Stripe" in read(client, "/services/search?q=bank") and len(tries) == 2


def test_a_known_maker_without_a_title_is_named_by_its_maker(project, client, monkeypatch):
    untitled = {"servers": [{"server": {"name": "com.stripe/mcp", "remotes": [
        {"type": "streamable-http", "url": "https://stripe.example.test/mcp"}]}}]}
    monkeypatch.setattr(connections, "_fetch_catalogue", lambda query: untitled)

    found = connections.search("stripe")["known"][0]

    assert found["title"] == "Stripe"


def test_versions_of_one_service_are_listed_once(project, client, monkeypatch):
    twice = {"servers": [CATALOGUE["servers"][0], CATALOGUE["servers"][0]]}
    monkeypatch.setattr(connections, "_fetch_catalogue", lambda query: twice)

    assert len(connections.search("bank")["others"]) == 1
