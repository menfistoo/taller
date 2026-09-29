"""One ticket's page: the ask, the plan, the verdicts, the change (spec 12).

Everything she needs to approve or reject without opening a terminal - read
from `main` and from the ticket's branch, and cut when it is too big to send to
a browser. A ticket whose branch is gone still shows what `main` kept.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import support
import cockpit
from cockpit import reading
from taller import discovery, gates, tickets


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    return support.new_project()


@pytest.fixture
def client(project):
    return cockpit.create_app(testing=True).test_client()


def at_review(project: Path, *, plan: str = "1. Use the danger token.\n",
              review: str = "The heading uses the danger token.\n",
              change: str = "h1 { color: var(--color-danger); }\n") -> dict:
    """A ticket at ⑦ with its papers and a real change on its branch."""
    ticket = tickets.create(project, title="Heading colour",
                            words="The red is wrong.\nUse the brand's own red.", kind="bug")
    ticket.update({"branch": "ticket/0001-heading-colour", "stage": "review", "lane": "fast",
                   "gates": ["constitution", "tests"],
                   "verdicts": {
                       "constitution": {"result": "fail", "blocker": 0, "high": 0, "medium": 1,
                                        "low": 0, "nit": 0, "hub_sha": "a3f9c21"},
                       "tests": {"result": "pass", "blocker": 0, "high": 0, "medium": 0,
                                 "low": 0, "nit": 0, "hub_sha": "a3f9c21"}}})
    ticket["checkpoints"]["review"] = "pending"
    written = tickets.write(project, ticket, "ticket 0001: at review")

    support.git(project, "branch", written["branch"], "main")
    tree = tickets._worktree(project, written)
    tree.parent.mkdir(parents=True, exist_ok=True)
    support.git(project, "worktree", "add", "--quiet", str(tree), written["branch"])
    folder = tree / tickets.ticket_dir(written)
    folder.mkdir(parents=True, exist_ok=True)
    support.write(folder / "plan.md", plan)
    support.write(folder / "review.md", review)
    (folder / "gates").mkdir(exist_ok=True)
    (folder / "gates" / "constitution.md").write_bytes(gates.render_verdict(
        {"gate": "constitution", "result": "fail", "metrics": {},
         "findings": [gates.finding("constitution.commit-message-shape", "", 0,
                                    'Commit 1a2b3c4 is titled "Fixed the colour".')]},
        hub_sha="a3f9c21", prose="One commit's subject is not the conventional form."))
    support.write(tree / "static" / "css" / "app.css", change)
    support.git(tree, "add", "--all")
    support.git(tree, "commit", "--quiet", "-m", "fix(ui): the heading colour")
    return written


def test_the_page_shows_the_ask_the_plan_and_the_review(project, client):
    at_review(project)

    page = client.get("/ticket/toolshed/1").get_data(as_text=True)

    assert "The red is wrong." in page
    assert "Use the danger token." in page
    assert "The heading uses the danger token." in page


def test_every_verdict_and_its_findings_are_shown(project, client):
    at_review(project)

    page = client.get("/ticket/toolshed/1").get_data(as_text=True)

    assert "constitution" in page and "tests" in page
    assert "constitution.commit-message-shape" in page
    assert "Fixed the colour" in page


def test_the_changed_files_are_listed_with_their_line_counts(project, client):
    at_review(project)

    found = reading.ticket_page("toolshed", 1)

    changed = found["diff"]["files"]
    assert [f["path"] for f in changed] == ["static/css/app.css"]
    assert changed[0]["added"] >= 1 and changed[0]["removed"] >= 1


def test_a_ticket_whose_branch_is_gone_still_renders(project, client):
    ticket = at_review(project)
    support.git(project, "worktree", "remove", "--force",
                str(tickets._worktree(project, ticket)))
    support.git(project, "branch", "-D", ticket["branch"])

    page = client.get("/ticket/toolshed/1").get_data(as_text=True)
    found = reading.ticket_page("toolshed", 1)

    assert "The red is wrong." in page                 # the ask lives on main
    assert found["gone"] and ticket["branch"] in " ".join(found["gone"])
    assert found["plan"] is None


def test_a_huge_plan_is_cut_with_a_line_saying_so(project, client):
    at_review(project, plan="1. Do it.\n" + ("x" * 40_000))

    found = reading.ticket_page("toolshed", 1)

    assert len(found["plan"]) <= reading.PAPER_MAX + 200
    assert "cut" in found["plan"].lower()


def test_a_diff_of_many_files_is_summarised(project, client):
    ticket = at_review(project)
    tree = tickets._worktree(project, ticket)
    for n in range(reading.DIFF_FILES_MAX + 10):
        support.write(tree / "static" / "css" / f"extra{n}.css", f".x{n} {{ margin: 0; }}\n")
    support.git(tree, "add", "--all")
    support.git(tree, "commit", "--quiet", "-m", "chore: many files")

    found = reading.ticket_page("toolshed", 1)

    assert len(found["diff"]["files"]) == reading.DIFF_FILES_MAX
    assert found["diff"]["cut"] is True
    assert found["diff"]["total"] > reading.DIFF_FILES_MAX


def test_an_unknown_ticket_is_a_plain_not_found(project, client):
    answer = client.get("/ticket/toolshed/99")

    assert answer.status_code == 404
    assert "99" in answer.get_data(as_text=True)


def test_reading_a_file_from_a_branch_is_one_function_now():
    import inspect

    from taller import chief, prs

    assert hasattr(tickets, "on_branch")
    assert "_on_branch" not in inspect.getsource(prs)
    assert "def _on_branch" not in inspect.getsource(chief)


# --- part two: the third action, and the pull request as GitHub has it -------

def token(client) -> dict:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def test_the_change_form_is_only_offered_while_it_would_mean_something(project, client):
    tickets.create(project, title="Heading colour", words="The red is wrong.", kind="bug")

    early = client.get("/ticket/toolshed/1").get_data(as_text=True)
    at_review(project)
    late = client.get("/ticket/toolshed/2").get_data(as_text=True)

    assert "Change what you asked for" in early
    assert "Change what you asked for" not in late


def test_changing_the_ask_from_the_browser_writes_it(project, client):
    tickets.create(project, title="Heading colour", words="The red is wrong.", kind="bug")

    client.post("/ticket/toolshed/1/change", follow_redirects=True,
                data={**token(client), "title": "The heading colour",
                      "words": "Use the brand's own red."})

    ticket = tickets.load(project, 1)
    assert ticket["title"] == "The heading colour"
    assert tickets._words(project, ticket).strip() == "Use the brand's own red."


def test_changing_the_ask_after_the_work_started_says_what_to_do_instead(project, client):
    at_review(project)

    answer = client.post("/ticket/toolshed/1/change", follow_redirects=True,
                         data={**token(client), "title": "Heading", "words": "Different."})

    page = answer.get_data(as_text=True)
    assert "reject" in page.lower()
    assert tickets._words(project, tickets.load(project, 1)).strip() != "Different."


def test_the_pull_request_is_shown_as_github_has_it(project, client, monkeypatch):
    from taller import discovery, issues

    ticket = at_review(project)
    ticket["pr"] = 7
    tickets.write(project, ticket, "ticket 0001: a pull request")
    monkeypatch.setattr(issues, "repo_of", lambda path: "neighbourhood/toolshed")
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: support.gh_json(
        {"state": "MERGED", "url": "https://github.com/neighbourhood/toolshed/pull/7",
         "mergeable": "UNKNOWN", "statusCheckRollup": []}))

    page = client.get("/ticket/toolshed/1").get_data(as_text=True)

    assert "merged" in page.lower()
    assert "https://github.com/neighbourhood/toolshed/pull/7" in page


def test_github_being_unreachable_is_one_line_not_a_broken_page(project, client, monkeypatch):
    from taller import discovery, issues

    ticket = at_review(project)
    ticket["pr"] = 7
    tickets.write(project, ticket, "ticket 0001: a pull request")
    monkeypatch.setattr(issues, "repo_of", lambda path: "neighbourhood/toolshed")
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)

    answer = client.get("/ticket/toolshed/1")

    assert answer.status_code == 200
    assert "gh" in answer.get_data(as_text=True)
