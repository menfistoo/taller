"""The twelve questions as a web form (spec 11, 12).

"The onboarding wizard runs in the cockpit as a web form using the identical
question list, by calling the same library code." So it does: the page renders
`onboarding.QUESTIONS`, every answer is validated by `onboarding.ask_one`, and
the answers file is the one a terminal reads - an interview started in one
carries on in the other.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import support
import cockpit
from cockpit import interview
from taller import brands, discovery, hub, onboarding, registry


@pytest.fixture
def ready(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    """A hub that has been through `taller setup`, and nothing else."""
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    support.new_project("boathouse")       # fills the hub and its catalogue
    return tmp_home / "projects"


@pytest.fixture
def client(ready):
    return cockpit.create_app(testing=True).test_client()


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


ANSWERS = {
    "what_it_does": "Keeps track of which neighbour has borrowed which tool.",
    "what_it_is_not": "It will never take payments.",
    "must_never_break": "Knowing who has which tool right now.",
    "users": "solo", "reach": "this machine", "phone": "n",
    "stores": "The tools, the neighbours, and who borrowed what.",
    "sensitive_data": "n", "profile": None, "brand": "none", "deploy": "local",
    "first_version": "A page listing my tools\nA form to record a loan",
}


def answer_them_all(client, name: str, ready: Path) -> None:
    client.post("/new", data={**token(client), "name": name, "path": str(ready)},
                follow_redirects=True)
    for question in onboarding.QUESTIONS:
        raw = ANSWERS[question.key]
        if raw is None:                       # the profile: whichever the hub has
            raw = interview.page(name)["choices"][0][0]
        client.post(f"/new/{name}", data={**token(client), "key": question.key,
                                          "value": raw}, follow_redirects=True)


def test_the_questions_are_the_same_twelve_in_the_same_order(client, ready):
    client.post("/new", data={**token(client), "name": "toolshed", "path": str(ready)},
                follow_redirects=True)

    found = interview.page("toolshed")
    page = client.get("/new/toolshed").get_data(as_text=True)

    assert found["total"] == 12 == len(onboarding.QUESTIONS)
    assert found["question"].key == onboarding.QUESTIONS[0].key
    assert onboarding.QUESTIONS[0].text in page
    assert onboarding.QUESTIONS[0].example in page


def test_an_answer_is_validated_by_the_same_code_the_terminal_uses(ready):
    interview.start("toolshed", str(ready))

    refused = interview.answer("toolshed", "users", "not one of them")
    taken = interview.answer("toolshed", "users", "solo")

    assert refused["ok"] is False and refused["problem"]
    assert taken["ok"] is True
    assert onboarding.load_progress("toolshed")["users"] == "solo"


def test_the_answers_file_is_the_one_the_terminal_reads(ready):
    interview.start("toolshed", str(ready))

    interview.answer("toolshed", "what_it_does", "Keeps track of tools.")

    assert onboarding.load_progress("toolshed")["what_it_does"] == "Keeps track of tools."


def test_an_interview_started_in_a_terminal_carries_on_in_the_browser(ready):
    onboarding.save_progress("toolshed", {"what_it_does": "Keeps track of tools."})
    interview.start("toolshed", str(ready))

    found = interview.page("toolshed")

    assert found["answered"] == 1
    assert found["question"].key == onboarding.QUESTIONS[1].key


def test_the_brief_is_shown_before_anything_is_created(client, ready):
    answer_them_all(client, "toolshed", ready)

    found = interview.page("toolshed")
    page = client.get("/new/toolshed").get_data(as_text=True)

    assert found["question"] is None and found["answered"] == 12
    assert "Keeps track of which neighbour" in page
    assert not (ready / "toolshed").exists()
    assert "toolshed" not in [entry["name"] for entry in registry.list_projects()]


def test_creating_it_makes_the_project_and_forgets_the_answers(client, ready):
    answer_them_all(client, "toolshed", ready)

    client.post("/new/toolshed/create", data=token(client), follow_redirects=True)

    assert (ready / "toolshed" / ".taller").is_dir()
    assert "toolshed" in [entry["name"] for entry in registry.list_projects()]
    assert onboarding.load_progress("toolshed") == {}


def test_a_second_tab_cannot_create_it_twice(client, ready):
    answer_them_all(client, "toolshed", ready)
    client.post("/new/toolshed/create", data=token(client), follow_redirects=True)

    again = client.post("/new/toolshed/create", data=token(client), follow_redirects=True)

    page = again.get_data(as_text=True)
    assert "Traceback" not in page
    assert "already exists" in page, "it must not report her answers as missing"
    assert len([e for e in registry.list_projects() if e["name"] == "toolshed"]) == 1


def test_a_name_that_is_not_a_name_is_refused(client, ready):
    refused = interview.start("Tool Shed!", str(ready))

    assert refused["problem"] and "name" in refused["problem"].lower()
    assert not onboarding.load_progress("Tool Shed!")


def test_a_folder_with_something_in_it_is_refused(client, ready, tmp_home):
    (ready / "toolshed").mkdir(parents=True)
    support.write(ready / "toolshed" / "already-here.txt", "mine\n")

    refused = interview.start("toolshed", str(ready))

    assert refused["problem"] and "empty" in refused["problem"].lower()


def test_a_hub_that_is_not_set_up_says_so_instead_of_asking_twelve_questions(tmp_home):
    hub.ensure_repo()                       # a hub with no language round

    refused = interview.start("toolshed", str(tmp_home / "projects"))

    assert "taller setup" in refused["problem"]


def test_making_a_brand_is_not_offered_here(client, ready):
    interview.start("toolshed", str(ready))
    for question in onboarding.QUESTIONS:
        if question.key == "brand":
            break
        interview.answer("toolshed", question.key,
                         interview.page("toolshed")["choices"][0][0]
                         if question.kind == "choice" else ANSWERS[question.key])

    found = interview.page("toolshed")

    assert found["question"].key == "brand"
    assert onboarding.NEW_BRAND not in [value for value, _ in found["choices"]]
    assert "taller brand new" in found["note"]


def test_starting_an_interview_needs_the_token(client, ready):
    answer = client.post("/new", data={"name": "toolshed", "path": str(ready)})

    assert answer.status_code == 400
    assert onboarding.load_progress("toolshed") == {}
