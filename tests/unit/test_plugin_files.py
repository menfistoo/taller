"""The plugin's own files: manifest, marketplace, seven commands, one hook.

Spec 3.5 (the command set and its naming), 10.1 (the layout). The commands are
instructions a chat follows, so what can be checked mechanically is checked
here: the set, the frontmatter, that each may run only `taller`, and that each
names its own verb, the answers file and the NEEDS loop. Plugin plan, Task 5.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = {
    "new": "taller ticket new",
    "approve": "taller ticket approve",
    "reject": "taller ticket reject",
    "resume": "taller ticket resume",
    "status": "taller ticket list",
    "amend": "taller amend",
    "onboard": "taller project new",
}
TALLER_ONLY = re.compile(r"^Bash\(taller [a-z -]+:\*\)$")


def front_matter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name} has no front matter"
    head, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(head), body


def test_the_manifest_names_the_plugin_taller():
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    version = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]

    assert manifest["name"] == "taller" and manifest["description"]
    assert manifest["version"] == version


def test_the_marketplace_installs_it_from_this_repository():
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text("utf-8"))

    assert market["name"] == "taller" and market["owner"]["name"]
    assert [(p["name"], p["source"]) for p in market["plugins"]] == [("taller", "./")]


def test_exactly_the_seven_commands_exist_named_by_verb():
    assert sorted(p.stem for p in (ROOT / "commands").glob("*.md")) == sorted(COMMANDS)


@pytest.mark.parametrize("verb", sorted(COMMANDS))
def test_each_command_has_frontmatter_and_only_taller_bash(verb):
    meta, _ = front_matter(ROOT / "commands" / f"{verb}.md")

    assert meta["description"] and "argument-hint" in meta
    tools = [t.strip() for t in str(meta["allowed-tools"]).split(",")]
    assert tools and all(TALLER_ONLY.match(tool) for tool in tools), tools


@pytest.mark.parametrize("verb, command", sorted(COMMANDS.items()))
def test_each_command_runs_its_own_taller_verb(verb, command):
    _, body = front_matter(ROOT / "commands" / f"{verb}.md")

    assert command in body.replace("--answers <answers file> ", "")


@pytest.mark.parametrize("verb", ["new", "approve", "resume"])
def test_long_runs_go_to_the_background(verb):
    _, body = front_matter(ROOT / "commands" / f"{verb}.md")

    assert "taller ticket run" in body and "background" in body


@pytest.mark.parametrize("verb", sorted(COMMANDS))
def test_every_command_handles_needs(verb):
    _, body = front_matter(ROOT / "commands" / f"{verb}.md")

    assert "--answers" in body and "NEEDS" in body


def test_the_hook_calls_the_cli():
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text("utf-8"))["hooks"]
    start = hooks["SessionStart"]

    assert [h["command"] for entry in start for h in entry["hooks"]] == [
        "taller hook session-start"]
    assert "startup" in start[0]["matcher"]


def test_the_owner_can_read_how_to_install_it():
    text = (ROOT / "docs" / "plugin.md").read_text("utf-8")

    assert "claude plugin marketplace add" in text and "taller@taller" in text
    for verb in COMMANDS:
        assert f"/taller:{verb}" in text
