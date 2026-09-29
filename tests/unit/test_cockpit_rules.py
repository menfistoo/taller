"""The Constitution screen: the rules read, and amended (spec 4.3-4.6, 12).

Saving here is `taller amend`: the file is written, committed under the hub lock
when it is the hub's, and every project the change reaches has its snapshot
refreshed. A rule that changed without the snapshots moving would be a rule
nothing enforces.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import support
import cockpit
from cockpit import rules
from taller import discovery, gitio, paths


@pytest.fixture
def project(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    return support.new_project()


@pytest.fixture
def client(project):
    return cockpit.create_app(testing=True).test_client()


def token(client) -> dict[str, str]:
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return {cockpit.TOKEN_FIELD: page.split(marker, 1)[1].split('"', 1)[0]}


def source_of(found: dict, where: str) -> dict:
    """The first source file of the first slice that has one from `where`."""
    for slice_ in found["slices"]:
        for source in slice_["sources"]:
            if source["where"] == where:
                return source
    raise AssertionError(f"no {where} source in {[s['name'] for s in found['slices']]}")


def head(repo: Path) -> str:
    return gitio.git(repo, "rev-parse", "HEAD").stdout.strip()


def test_every_slice_shows_its_files_and_where_they_come_from(project, client):
    found = rules.slices("toolshed")
    page = client.get("/rules?project=toolshed").get_data(as_text=True)

    assert [slice_["name"] for slice_ in found["slices"]]
    assert any(source["where"] == "hub"
               for slice_ in found["slices"] for source in slice_["sources"])
    assert source_of(found, "hub")["text"].strip()
    assert found["branch"] == "main"
    assert "conventions" in page


def test_saving_a_project_rule_commits_it_and_refreshes_the_snapshot(project, client):
    rules.save("toolshed", str(paths.project_constitution(project) / "conventions.md"),
               "# Conventions\n\nTabs are out; four spaces.\n", "Tabs are out")

    log = gitio.git(project, "log", "--format=%s", "-3").stdout
    snapshot = (project / ".taller" / "resolved.json").read_text(encoding="utf-8")
    assert "amend: Tabs are out" in log
    assert "Tabs are out; four spaces." in snapshot


def test_saving_a_hub_rule_refreshes_every_project_that_uses_it(project, client):
    found = rules.slices("toolshed")
    source = source_of(found, "hub")

    lines = rules.save("toolshed", source["path"],
                       source["text"] + "\n- Never use a bare except.\n",
                       "Bare excepts hide the cause")

    assert "amend: Bare excepts hide the cause" in gitio.git(paths.hub(), "log",
                                                             "--format=%s", "-2").stdout
    assert any("toolshed" in line for line in lines)
    assert "Never use a bare except." in (project / ".taller" / "resolved.json").read_text("utf-8")


def test_a_rule_cannot_be_amended_while_the_project_is_on_a_ticket_branch(project, client):
    support.git(project, "checkout", "--quiet", "-b", "ticket/0001-heading")
    before = head(project)
    path = str(paths.project_constitution(project) / "conventions.md")

    answer = client.post("/rules/toolshed", follow_redirects=True,
                         data={**token(client), "path": path, "text": "# Changed\n",
                               "reason": "while on a branch"})

    page = answer.get_data(as_text=True)
    assert "main" in page and "ticket/0001-heading" in page
    assert head(project) == before
    assert gitio.git(project, "status", "--porcelain").stdout.strip() == ""


def test_a_path_that_is_not_one_of_the_files_is_refused(project, client, tmp_home):
    elsewhere = tmp_home / "not-a-rule.txt"

    answer = client.post("/rules/toolshed", follow_redirects=True,
                         data={**token(client), "path": str(elsewhere),
                               "text": "anything at all", "reason": "trying it on"})

    page = answer.get_data(as_text=True)
    assert "is not one of" in page
    assert not elsewhere.exists(), "a form field wrote a file outside the rules"


def test_a_path_climbing_out_of_the_hub_is_refused(project, client, tmp_home):
    climbing = str(paths.modules() / ".." / ".." / "escaped.md")

    answer = client.post("/rules/toolshed", follow_redirects=True,
                         data={**token(client), "path": climbing, "text": "no",
                               "reason": "trying it on"})

    assert "is not one of" in answer.get_data(as_text=True)
    assert not (tmp_home / "escaped.md").exists()


def test_an_amendment_with_no_reason_is_refused(project, client):
    before = head(project)

    answer = client.post("/rules/toolshed", follow_redirects=True,
                         data={**token(client), "text": "# Changed\n", "reason": "   ",
                               "path": str(paths.project_constitution(project)
                                           / "conventions.md")})

    page = answer.get_data(as_text=True)
    assert "reason" in page.lower()
    assert head(project) == before


def test_amending_needs_the_token(project, client):
    before = head(project)

    answer = client.post("/rules/toolshed",
                         data={"path": str(paths.project_constitution(project)
                                           / "conventions.md"),
                               "text": "# Changed\n", "reason": "no token"})

    assert answer.status_code == 400
    assert head(project) == before


def test_the_overrides_are_shown_with_the_rules(project, client):
    support.write(paths.project_constitution(project) / "overrides.md",
                  "---\noverrides:\n  - rule: size.file-too-long\n"
                  "    scope: \"legacy/report.py\"\n    reason: \"Split ticket by ticket.\"\n"
                  "---\n\nIt is being split.\n")
    support.git(project, "add", "--all")
    support.git(project, "commit", "--quiet", "-m", "docs: an override")

    found = rules.slices("toolshed")
    page = client.get("/rules?project=toolshed").get_data(as_text=True)

    assert [o["rule"] for o in found["overrides"]] == ["size.file-too-long"]
    assert "Split ticket by ticket." in page
