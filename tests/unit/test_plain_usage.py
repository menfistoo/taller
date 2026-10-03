"""What it uses (phase G2, Task 4): which Claude does each job, and where her plan went.

One page, reached from every plain page. Who does what names the model that
actually ran for each job - the configuration only says what was asked for - and
offers the strongest model for writing plans and for checking safety, off by
default. How much each thing used is a bar against her largest, with where it
went in words. What goes with every request is Task 1's switch. The word for
what the machine counts never appears.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

import support
import cockpit
from cockpit import usage, words
from taller import config, discovery, hub, tickets

# Model names are shown on purpose, as people say them ("Claude Haiku 4.5");
# what the machine calls them ("claude-haiku-4-5") is not.
MACHINE = ("token", "gate", "role", "alias", "explorer", "architect", "weighted", "by_role",
           "claude-")


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    return support.new_project()


@pytest.fixture
def client(project):
    return cockpit.create_app(testing=True).test_client()


def tokens(n: int) -> dict[str, int]:
    return {"input": n, "cache_write": 0, "cache_read": 0, "output": 0}


def spent(project: Path, title: str, weighted: int, *, by_role: dict | None = None,
          ran: dict | None = None, created: str = "2026-09-29T09:00:00") -> None:
    made = tickets.create(project, title=title, words=title, kind="bug")
    ticket = tickets.load(project, int(made["id"]))
    block = {"by_model": {"claude-haiku-4-5": tokens(weighted)}, "total_tokens": weighted,
             "weighted_tokens": weighted, "cost": None, "partial": False, "sessions": []}
    if by_role is not None:
        block["by_role"] = {role: tokens(n) for role, n in by_role.items()}
    if ran is not None:
        block["ran"] = ran
    ticket["spend"] = block
    ticket["created"] = created
    tickets.write(project, ticket, f"ticket {int(made['id']):04d}: spend")


@pytest.fixture
def project_with_spend(project):
    spent(project, "The loans list doesn't match", 300_000,
          by_role={"explorer": 250_000, "chief": 50_000},
          ran={"explorer": "claude-haiku-4-5-20251001", "architect": "claude-fable-5-1",
               "chief": "claude-sonnet-5-5"},
          created="2026-09-30T09:00:00")
    spent(project, "Add a due date", 100_000, by_role={"implementer": 90_000, "chief": 10_000},
          created="2026-09-29T09:00:00")
    spent(project, "Sort the list", 20_000, by_role={"gate_quality": 20_000},
          created="2026-09-28T09:00:00")
    return project


def read(client, where: str = "/usage") -> str:
    page = client.get(where).get_data(as_text=True)
    page = re.sub(r"(?s)<(style|script)\b.*?</\1>", " ", page)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def job(found: dict, name: str) -> dict:
    return next(j for j in found["jobs"] if j["name"] == name)


def test_each_job_names_the_model_that_actually_ran(project_with_spend, client):
    found = usage.usage()
    page = read(client)

    assert job(found, "Reading your project")["model"] == "Claude Haiku 4.5"
    assert job(found, "Writing plans")["model"] == "Claude Fable 5.1", "what ran, not the setting"
    assert job(found, "Understanding what you asked for")["model"] == "Claude Sonnet 5.5"
    assert "Reading your project Claude Haiku 4.5 quick and light" in page


def test_a_job_that_has_not_run_yet_names_the_model_it_will_use(project, client):
    assert job(usage.usage(), "Writing plans")["model"] == "Claude Opus 5.5"


def test_the_checks_name_the_model_for_safety_when_it_differs(project, client):
    assert job(usage.usage(), "Checking the work")["extra"] == "Opus 5.5 for safety"


def test_fable_is_offered_for_plans_and_safety_and_off_by_default(project, client):
    page = read(client)

    assert usage.usage()["strongest"] == {"plans": False, "safety": False}
    assert "Use the strongest for writing plans" in page
    assert "Use the strongest for checking safety" in page
    assert "Claude Fable 5.1" in page


def test_turning_on_the_strongest_for_plans_writes_the_hub(project, client):
    client.post("/usage/strongest", follow_redirects=True,
                data={**token(client), "job": "plans", "on": "1"})

    assert hub.read_config()["models"]["architect"] == "creative"
    assert usage.usage()["strongest"]["plans"] is True

    client.post("/usage/strongest", follow_redirects=True,
                data={**token(client), "job": "plans", "on": "0"})
    assert config.load_hub_config()["models"]["architect"] == "thinker"


def test_a_job_that_is_not_offered_is_refused(project, client):
    client.post("/usage/strongest", follow_redirects=True,
                data={**token(client), "job": "chief", "on": "1"})

    assert config.load_hub_config()["models"]["chief"] == "worker"


def test_each_thing_says_where_its_usage_went(project_with_spend, client):
    page = read(client)

    assert "The loans list doesn't match" in page
    assert "toolshed · mostly reading your project" in page
    assert "toolshed · mostly making the change" in page


def test_the_biggest_comes_first_and_sets_the_scale(project_with_spend):
    things = usage.usage()["things"]

    assert [t["title"] for t in things][0] == "The loans list doesn't match"
    assert things[0]["width"] == 100 and 0 < things[-1]["width"] < things[0]["width"]


def test_more_than_usual_is_twice_her_median(project_with_spend, client):
    things = {t["title"]: t for t in usage.usage()["things"]}

    assert things["The loans list doesn't match"]["more"] is True
    assert things["Add a due date"]["more"] is False
    assert "more than usual" in read(client)


def test_a_thing_from_before_usage_by_job_says_nothing_rather_than_guessing(project, client):
    spent(project, "An old one", 50_000)

    found = usage.usage()["things"][0]

    assert found["where"] == ""
    assert "mostly" not in read(client)


def test_leaving_her_setup_out_is_on_and_can_be_turned_off(project, client):
    assert usage.usage()["leave_out"] is True
    assert "Leave my connected services and plugins out" in read(client)

    client.post("/usage/leave-out", follow_redirects=True, data={**token(client), "on": "0"})

    assert config.load_hub_config()["dispatch"]["leave_out_my_setup"] is False


def test_the_word_token_appears_nowhere(project_with_spend, client):
    page = read(client).lower()

    assert [word for word in MACHINE if re.search(rf"\b{word}", page)] == []


def test_every_plain_page_links_here(project, client):
    for where in ("/", "/ask", "/project/toolshed/about"):
        assert 'href="/usage"' in client.get(where).get_data(as_text=True), where
