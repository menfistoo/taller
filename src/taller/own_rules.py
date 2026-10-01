"""Her own rules: what a project must always do, and must never do, in her words.

They live in the project's own constitution - `always` under a heading in
`product.md`, `never` under the same heading in `never.md` - so they reach the
resolved snapshot every check reads. The rest of those two files is written from
the twelve answers; this section is hers, and `scaffold` carries it over whenever
the answers are written again.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from . import generated, gitio, locking, paths, registry
from .errors import ConfigError, NotOnMain

OWN_HEADING = "## Your own rules"
FILES = {"always": "product.md", "never": "never.md"}
_RULE = re.compile(r"^- (.+)$")
_WHY = re.compile(r"^  (.*?)\s*\(added (\d{4}-\d{2}-\d{2})\)$")

Rule = dict[str, str]


def read(project: Path | str) -> dict[str, list[Rule]]:
    """{"always": [...], "never": [...]}, each rule {"text", "why", "added"}."""
    project = Path(project)
    return {kind: _parse(_section(_file(project, kind)))
            for kind in FILES}


def add(project: Path | str, kind: str, text: str, why: str = "") -> list[str]:
    """Add one rule, committed on `main` and reaching the snapshot. Lines to show her."""
    text = " ".join(str(text).split())
    if not text:
        raise ConfigError("A rule needs words: what should it always, or never, do?")
    rules = read(project)[_kind(kind)]
    rules.append({"text": text, "why": " ".join(str(why).split()),
                  "added": date.today().isoformat()})
    return _write(Path(project), kind, rules, why.strip() or text)


def remove(project: Path | str, kind: str, index: int, why: str) -> list[str]:
    """Take one rule away. A reason is required: it is what the history keeps."""
    why = " ".join(str(why).split())
    if not why:
        raise ConfigError("Removing a rule needs a reason; it is kept with the change.")
    rules = read(project)[_kind(kind)]
    if not 0 <= index < len(rules):
        raise ConfigError("There is no such rule any more; the page may be out of date.")
    del rules[index]
    return _write(Path(project), kind, rules, why)


def carry_over(existing: str | None) -> str:
    """The own-rules section of a file about to be rewritten, or "" when it has none."""
    section = _section(existing)
    return f"\n{OWN_HEADING}\n\n{section}" if section.strip() else ""


def _write(project: Path, kind: str, rules: list[Rule], reason: str) -> list[str]:
    entry = registry.get_project(project)
    branch = gitio.git(project, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != gitio.MAIN_BRANCH:
        # A rule written on a ticket branch would vanish with the branch.
        raise NotOnMain(f"{entry['name']} is on {branch}. A rule is changed on "
                          f"{gitio.MAIN_BRANCH}: switch to it, then try again.")
    target = paths.project_constitution(project) / FILES[kind]
    with locking.project_lock(entry["name"]):
        body = (_file(project, kind) or "").split(f"\n{OWN_HEADING}", 1)[0].rstrip("\n")
        section = "\n".join(_render(rule) for rule in rules)
        text = body + (f"\n\n{OWN_HEADING}\n\n{section}\n" if rules else "\n")
        locking.atomic_write_text(target, text)
    relative = target.relative_to(project).as_posix()
    gitio.git(project, "add", "--", relative)
    gitio.git(project, "commit", "--quiet", "-m", f"amend: {reason}", "--", relative)
    sync = generated.refresh(project)
    return [f"Changed {entry['name']}'s rules; its checks now use them (sync: {sync})."]


def _render(rule: Rule) -> str:
    """`- the rule`, then `  why (added YYYY-MM-DD)` - the why may be empty."""
    added = rule.get("added") or date.today().isoformat()
    why = f"{rule['why']} " if rule.get("why") else ""
    return f"- {rule['text']}\n  {why}(added {added})"


def _parse(section: str) -> list[Rule]:
    rules: list[Rule] = []
    for line in section.splitlines():
        found = _RULE.match(line)
        if found:
            rules.append({"text": found.group(1).strip(), "why": "", "added": ""})
            continue
        why = _WHY.match(line)
        if why and rules:
            rules[-1]["why"] = why.group(1).strip()
            rules[-1]["added"] = why.group(2)
    return rules


def _section(text: str | None) -> str:
    if not text or f"\n{OWN_HEADING}" not in f"\n{text}":
        return ""
    return f"\n{text}".split(f"\n{OWN_HEADING}", 1)[1].lstrip("\n")


def _file(project: Path, kind: str) -> str | None:
    target = paths.project_constitution(project) / FILES[_kind(kind)]
    return target.read_text(encoding="utf-8") if target.is_file() else None


def _kind(kind: str) -> str:
    if kind not in FILES:
        raise ConfigError(f"A rule is either always or never, not {kind!r}.")
    return kind

