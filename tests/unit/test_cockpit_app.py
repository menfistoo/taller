"""The cockpit's application: this machine only, and a token on every form.

Spec 12 and 1.1 - Flask, bound to 127.0.0.1, no authentication, single
operator. No auth is not the same as no protection: a page on any other site
can post to 127.0.0.1 in her browser, so every form carries a token this
application made and checks.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

import support
import cockpit
from taller import cli, discovery
from taller.prompter import ScriptedPrompter


@pytest.fixture
def client(tmp_home: Path, identity, stub_claude, monkeypatch):
    monkeypatch.setattr(discovery, "_run_gh", lambda args, **kwargs: None)
    support.new_project()
    app = cockpit.create_app(testing=True)
    return app.test_client()


def token_of(client) -> str:
    """The token the application put in its own form."""
    page = client.get("/").get_data(as_text=True)
    marker = f'name="{cockpit.TOKEN_FIELD}" value="'
    return page.split(marker, 1)[1].split('"', 1)[0]


def test_the_app_serves_the_board_at_the_root(client):
    answer = client.get("/")

    assert answer.status_code == 200
    assert "Taller" in answer.get_data(as_text=True)


def test_a_post_without_the_token_is_refused(client):
    answer = client.post("/ticket/toolshed/1/approve", data={})

    assert answer.status_code == 400
    assert "token" in answer.get_data(as_text=True).lower()


def test_a_post_with_a_wrong_token_is_refused(client):
    answer = client.post("/ticket/toolshed/1/approve",
                         data={cockpit.TOKEN_FIELD: "not-the-token"})

    assert answer.status_code == 400


def test_a_post_with_the_token_gets_past_the_check(client):
    """Past the token check: what it then does is Task 4's business."""
    answer = client.post("/ticket/toolshed/1/approve",
                         data={cockpit.TOKEN_FIELD: token_of(client)})

    assert answer.status_code != 400


def test_the_page_carries_no_brand(client):
    page = client.get("/").get_data(as_text=True)

    assert "var(--brand" not in page and "tokens.css" not in page


def test_it_binds_this_machine_only(monkeypatch, tmp_home: Path, identity, stub_claude):
    from taller.commands import cockpit as command

    seen: dict[str, object] = {}
    monkeypatch.setattr(command, "_serve",
                        lambda app, host, port: seen.update(host=host, port=port))
    monkeypatch.setattr(command, "_open_in_browser", lambda url: None)

    code = cli.main(["cockpit"], ScriptedPrompter({}))

    assert code == 0
    assert seen["host"] == "127.0.0.1" and seen["port"] == command.DEFAULT_PORT


def test_a_port_already_in_use_is_reported_not_bound_over(tmp_home: Path, identity,
                                                          stub_claude, monkeypatch):
    from taller.commands import cockpit as command

    monkeypatch.setattr(command, "_open_in_browser", lambda url: None)
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    port = held.getsockname()[1]
    prompter = ScriptedPrompter({})
    try:
        code = cli.main(["cockpit", "--port", str(port)], prompter)
    finally:
        held.close()

    said = "\n".join(prompter.said)
    assert code == cli.EXIT_REFUSED
    assert str(port) in said and "--port" in said


def test_flask_is_a_dependency():
    import tomllib

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    assert any(dep.lower().startswith("flask") for dep in data["project"]["dependencies"])
