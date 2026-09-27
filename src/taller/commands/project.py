"""`taller project new`: setup if needed, twelve questions, the brief, the project.

Spec 11.1 and 11.4. Nothing is written into the project or the hub before the
brief is approved — the only file written earlier is the resume file, outside
every project. After approval `scaffold.create_project` does the work; this
module only holds the conversation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .. import brands, config, discovery, gitio, onboarding, scaffold
from ..errors import ConfigError
from ..onboarding import Question, ask
from ..prompter import Prompter
from . import brand as brand_command
from . import setup as setup_command


def default_parent() -> Path:
    """Where a new project goes when `--path` is not given (spec 4.7 round 2).

    Beside the repository the owner is standing in, if any — projects tend to
    live side by side — otherwise the current directory.
    """
    completed = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace")
    if completed.returncode == 0 and completed.stdout.strip():
        return Path(completed.stdout.strip()).parent
    return Path.cwd()


def new(args: Any, prompter: Prompter) -> int:
    name = args.name
    if not brands.SLUG.match(name or ""):
        raise ConfigError(f"{name!r} is not a usable project name: lowercase letters, "
                          f"digits and hyphens, starting with a letter or digit.")
    target = (Path(args.path) if args.path else default_parent()) / name
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ConfigError(f"{target} exists and is not empty. Choose another name or "
                          f"--path; `taller project adopt` is for an existing project.")
    open_pages = not args.no_open

    if setup_command.needed():
        setup_command.run_inline(prompter)

    prompter.say(f"\nNew project {name}, to be created in {target}")
    answers = onboarding.run(
        name, prompter,
        new_brand=lambda p: brand_command.create(p, open_page=open_pages),
    )

    if not _approve(name, prompter, answers, open_pages):
        prompter.say(f"Nothing was created. Your answers are kept: "
                     f"`taller project new {name}` picks up from here.")
        return 1

    report = scaffold.create_project(target, name=name, profile=answers["profile"],
                                     brand=answers["brand"], answers=answers)
    onboarding.discard_progress(name)

    remote = _offer_remote(name, target, prompter)
    _closing_report(name, report, answers, remote, prompter)
    return 0


def _approve(name: str, prompter: Prompter, answers: dict, open_pages: bool) -> bool:
    while True:
        page = onboarding.write_brief(name, answers)
        prompter.say("\n" + onboarding.brief_text(name, answers))
        prompter.say(f"\nThe brief is at {page}")
        if open_pages:
            brand_command.open_in_browser(page)
        decision = ask(prompter, Question(
            "brief", "brief", 0, "Create the project from this brief?", "choice",
            choices=(("approve", "approve and create it"), ("edit", "change an answer"),
                     ("cancel", "stop here"))))
        if decision == "approve":
            return True
        if decision == "cancel":
            return False
        while True:
            raw = prompter.ask("brief.edit", "  Which question, 1 to 12?").strip()
            if raw.isdigit() and 1 <= int(raw) <= 12:
                break
            prompter.say("  Please give a number from 1 to 12.")
        onboarding.edit(name, prompter, answers, int(raw),
                        new_brand=lambda p: brand_command.create(p, open_page=open_pages))


def _offer_remote(name: str, target: Path, prompter: Prompter) -> str | None:
    """Only if `gh` can, only if asked, and the default is no (spec 11.4, 13.2)."""
    status = discovery.gh_auth_status()
    if not status["ok"]:
        return None
    create = ask(prompter, Question(
        "remote", "remote", 0,
        f"Create a private GitHub repository for {name} under {status['account']} "
        f"and push it?", "yes_no", default=False))
    if not create:
        return None
    completed = discovery._run_gh(["repo", "create", name, "--private",
                                   "--source", str(target), "--remote", "origin",
                                   "--push"])
    if completed is None or completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip() if completed else ""
        prompter.say(f"The repository was not created: {detail or 'gh failed'}. "
                     f"The project is complete locally.")
        return None
    return f"{status['account']}/{name}"


def _closing_report(name: str, report: scaffold.CreateReport, answers: dict,
                    remote: str | None, prompter: Prompter) -> None:
    count = gitio.git(report.path, "rev-list", "--count", "HEAD").stdout.strip()
    pushed = f"pushed to {remote}" if remote else "not pushed: no remote"
    language = config.load_hub_config()["language"]
    brand = answers["brand"] if answers["brand"] != "none" else "no brand"
    queue = answers["first_version"]
    lines = [
        "",
        f"Created {name} at {report.path}   (branch main, {count} commits, {pushed})",
        f"  Profile {answers['profile']} · {brand} · UI language {language.get('ui')}",
        f"  Queue: {len(queue)} proposed piece{'s' if len(queue) != 1 else ''} of work "
        f"in .taller/queue.yml",
    ]
    lines += [f"    - {item}" for item in queue]
    lines.append(f"  Next: cd {report.path} && python -m pytest -q")
    prompter.say("\n".join(lines))
