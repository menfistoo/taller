"""The twelve questions, as a form (spec 11, 12).

"The onboarding wizard runs in the cockpit as a web form using the identical
question list, by calling the same library code." Nothing here asks a question
of its own or decides what a good answer is: the page renders
`onboarding.QUESTIONS`, and every answer goes through `onboarding.ask_one` with
a prompter holding exactly what she typed - so the browser and the terminal
accept and refuse the same things, and write the same answers file.

Two things this form cannot do, and says so rather than half-doing:
`taller setup` (its questions are about this machine, not about a project), and
making a new brand (that opens a page and asks for colours - its own screen).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from taller import brands, locking, onboarding, paths, prompter, scaffold
from taller.commands import setup as setup_command
from taller.errors import ConfigError, TallerError

BRAND_NOTE = ("A new brand is made with `taller brand new`, which opens a page and asks "
              "for its colours and fonts. Choose none for now; a brand can be set later.")


def started_dir() -> Path:
    """Where the folder chosen for each half-finished interview is kept.

    The answers file (spec 11.3) holds answers only, and where the project should
    go is not one of the twelve. A function, not a constant: the home directory
    is read when it is asked for.
    """
    return paths.run_dir() / "cockpit-new"


def start(name: str, path: str) -> dict[str, Any]:
    """Begin (or pick up) an interview. `problem` says why not, if not."""
    if setup_command.needed():
        return {"problem": "This hub has not been set up yet. Run `taller setup` in a "
                           "terminal first: it asks about this machine - your language, "
                           "how Claude is reached, where projects live - and it is what "
                           "makes everything else work."}
    if not brands.SLUG.match(name or ""):
        return {"problem": f"{name!r} is not a usable project name: lowercase letters, "
                           f"digits and hyphens, starting with a letter or digit."}
    target = Path(path or ".").expanduser() / name
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        return {"problem": f"{target} exists and is not empty. Choose another name or "
                           f"another folder; `taller project adopt` is for a project that "
                           f"already exists."}
    locking.atomic_write(started_dir() / f"{name}.json",
                         json.dumps({"target": str(target)}).encode("utf-8"))
    return {"name": name, "target": str(target), "problem": ""}


def page(name: str) -> dict[str, Any]:
    """The next question, or the brief once all twelve are answered."""
    answers = onboarding.load_progress(name)
    question = next((q for q in onboarding.QUESTIONS if q.key not in answers), None)
    return {
        "name": name,
        "target": _target(name),
        "question": question,
        "number": onboarding.QUESTIONS.index(question) + 1 if question else 12,
        "round": question.round if question else 4,
        "round_title": onboarding.ROUND_TITLES[question.round] if question else "",
        "choices": _choices(question, answers) if question else [],
        "note": BRAND_NOTE if question and question.key == "brand" else "",
        "answered": len(answers),
        "total": len(onboarding.QUESTIONS),
        "answers": answers,
        "brief": onboarding.brief_rows(answers) if question is None else [],
    }


def answer(name: str, key: str, raw: str | list[str]) -> dict[str, Any]:
    """Take one answer, judged by the same code the terminal uses."""
    question = next((q for q in onboarding.QUESTIONS if q.key == key), None)
    if question is None:
        return {"ok": False, "problem": f"There is no question {key!r}."}
    answers = onboarding.load_progress(name)
    sheet = prompter.AnswerSheetPrompter({question.id: raw})
    try:
        value = onboarding.ask_one(sheet, question, answers)
    except prompter.NeedsAnswer:
        # The library asked again, which is how it says "not that": the terminal
        # would have re-prompted, and the browser shows the question again.
        return {"ok": False, "problem": _refusal(question)}
    except TallerError as exc:
        return {"ok": False, "problem": str(exc)}
    answers[key] = value
    onboarding.save_progress(name, answers)
    return {"ok": True, "problem": "", "value": value}


def create(name: str) -> dict[str, Any]:
    """Make the project from the twelve answers - the same two calls the terminal makes."""
    answers = onboarding.load_progress(name)
    missing = [q.key for q in onboarding.QUESTIONS if q.key not in answers]
    if missing:
        raise ConfigError(f"{len(missing)} of the twelve are still unanswered, so there "
                          f"is nothing to create yet.")
    target = _target(name)
    if not target:
        raise ConfigError(f"Where {name} should go was not kept - start again from "
                          f"New project, and your answers will still be there.")
    report = scaffold.create_project(Path(target), name=name, profile=answers["profile"],
                                     brand=answers["brand"], answers=answers)
    onboarding.discard_progress(name)
    (started_dir() / f"{name}.json").unlink(missing_ok=True)
    return {"project": name, "target": target, "report": report}


def _target(name: str) -> str:
    try:
        kept = json.loads((started_dir() / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(kept.get("target") or "")


def _choices(question: onboarding.Question, answers: dict[str, Any]) -> list[tuple[str, str]]:
    """The options, exactly as the terminal offers them, minus the one this form
    cannot carry out."""
    if question.key == "profile":
        return list(onboarding.profile_choices())
    if question.key == "brand":
        return [(value, label) for value, label in onboarding.brand_choices()
                if value != onboarding.NEW_BRAND]
    return list(question.choices)


def _refusal(question: onboarding.Question) -> str:
    if question.kind == "yes_no":
        return "Please answer yes or no."
    if question.kind == "list":
        return "At least one piece of work is needed."
    if question.choices or question.key in ("profile", "brand"):
        return "Please choose one of the options."
    return "An answer is needed."
