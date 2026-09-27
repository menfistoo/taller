"""The twelve onboarding questions, asked one at a time, and the brief.

Spec 11.1. `taller project new` and (chunk 9) `taller project adopt` ask the
same twelve questions in four rounds; this module is that list and the loop
that asks it. Two properties matter more than any wording:

* **Resumable** (11.3). Every answer is written to
  `~/.taller-run/onboarding/<name>.yml` as it is given, so a dead session does
  not restart the interview. That file is the only thing written before the
  brief is approved.
* **Nothing is inferred.** Answers are the owner's own words. No question here
  spends the subscription window.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from . import brands, catalogue, locking, paths
from .errors import ConfigError
from .prompter import Prompter
from .scaffold import flatten

Answers = dict[str, Any]
Choice = tuple[str, str]                     # (value, label)

NEW_BRAND = "__new__"
ROUND_TITLES = {1: "what it is", 2: "who and where", 3: "data", 4: "shape"}
NUMERALS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫"


@dataclass(frozen=True)
class Question:
    id: str
    key: str                  # the answer's name in `scaffold.create_project`
    round: int
    text: str
    kind: str                 # text | choice | yes_no | list
    why: str = ""
    choices: tuple[Choice, ...] = field(default_factory=tuple)
    default: Any = None       # a choice value, a bool, or None for "must answer"

    @property
    def number(self) -> str:
        """① … ⑫ for the twelve; nothing for a question outside the list."""
        digits = self.id[1:]
        return NUMERALS[int(digits) - 1] if self.id[:1] == "q" and digits.isdigit() else "·"


QUESTIONS: tuple[Question, ...] = (
    Question("q1", "what_it_does", 1, "In one sentence, what does this do?", "text"),
    Question("q2", "what_it_is_not", 1, "What does it deliberately NOT do?", "text",
             why="Keeps it from quietly becoming a bigger tool. Nothing in the code "
                 "can answer this."),
    Question("q3", "must_never_break", 1, "What must never break?", "text"),
    Question("q4", "users", 2, "Who uses it?", "choice",
             why="Changing this later is a rewrite, so it is asked before any code exists.",
             choices=(("solo", "you alone"), ("team", "a team with roles"),
                      ("public", "the public"))),
    Question("q5", "reach", 2, "Reached from where?", "choice",
             choices=(("this machine", "this machine"),
                      ("a private network", "a private network"),
                      ("a VPN", "a VPN"), ("the internet", "the internet")),
             default="this machine"),
    Question("q6", "phone", 2, "Used on a phone?", "yes_no", default=False),
    Question("q7", "stores", 3, "What does it store?", "text"),
    Question("q8", "sensitive_data", 3,
             "Does any of it involve money, personal data, or credentials?", "yes_no",
             why="A yes makes the security review mandatory on those paths and adds "
                 "an audit log."),
    Question("q9", "profile", 4, "Profile", "choice",
             why="The stack. Profiles from the catalogue are copied into your hub "
                 "when first used."),
    Question("q10", "brand", 4, "Brand", "choice"),
    Question("q11", "deploy", 4, "Deploys where?", "choice",
             choices=(("local", "this machine only"),
                      ("docker", "a server, Docker Compose behind Caddy")),
             default="local"),
    Question("q12", "first_version", 4,
             "What is the smallest version that is actually useful to you?", "list",
             why="One piece of work per line; an empty line ends the list. Three to "
                 "five is right."),
)
BY_ID = {question.id: question for question in QUESTIONS}


# --- pickers (spec 4.7: never a typed slug) ----------------------------------

def profile_choices() -> list[Choice]:
    """The hub's profiles first, then what the catalogue offers."""
    hub = catalogue.installed_profiles()
    offered = [name for name in catalogue.list_profiles() if name not in hub]
    return ([(name, name) for name in hub]
            + [(name, f"{name} (from the catalogue)") for name in offered])


def brand_choices() -> list[Choice]:
    return ([("none", "none")] + [(slug, slug) for slug in brands.list_brands()]
            + [(NEW_BRAND, "new brand…")])


# --- asking ------------------------------------------------------------------

def ask(prompter: Prompter, question: Question,
        choices: tuple[Choice, ...] | list[Choice] | None = None,
        default: Any = None) -> Any:
    """Ask one question until the answer is valid. Never crashes on input."""
    options = tuple(choices if choices is not None else question.choices)
    default = default if default is not None else question.default
    prompt = _prompt(question, options, default)

    while True:
        if question.kind == "list":
            items = [flatten(line) for line in prompter.ask_lines(question.id, prompt)]
            items = [item for item in items if item]
            if items:
                return items
            prompter.say("  At least one piece of work is needed.")
            continue

        raw = prompter.ask(question.id, prompt).strip()
        if question.kind == "text":
            if flatten(raw):
                return flatten(raw)
            if default is not None:
                return default
            prompter.say("  An answer is needed.")
        elif question.kind == "yes_no":
            if not raw and default is not None:
                return default
            if raw.lower() in ("y", "yes"):
                return True
            if raw.lower() in ("n", "no"):
                return False
            prompter.say("  Please answer y or n.")
        else:                                        # choice
            if not raw and default is not None:
                return default
            value = _pick(raw, options)
            if value is not None:
                return value
            prompter.say(f"  Please choose a number from 1 to {len(options)}.")


def _pick(raw: str, options: tuple[Choice, ...]) -> str | None:
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1][0]
    for value, label in options:
        if raw.lower() in (value.lower(), label.lower()):
            return value
    return None


def _prompt(question: Question, options: tuple[Choice, ...], default: Any) -> str:
    lines = [f"  {question.number} {question.text}"]
    if question.why:
        lines.append(f"     ({question.why})")
    if options:
        lines.append("     " + "  ".join(f"{n}) {label}"
                                         for n, (_, label) in enumerate(options, 1)))
    if question.kind == "yes_no":
        lines.append("     [Y/n]" if default is True else "     [y/N]" if default is False
                     else "     [y/n]")
    elif default is not None and options:
        index = next(n for n, (value, _) in enumerate(options, 1) if value == default)
        lines.append(f"     [{index}]")
    return "\n".join(lines)


# --- the interview -----------------------------------------------------------

def run(name: str, prompter: Prompter, *,
        new_brand: Callable[[Prompter], str | None] | None = None) -> Answers:
    """All twelve, resuming from the answers file when there is one."""
    answers = load_progress(name)
    if answers:
        resume = ask(prompter, Question("resume", "resume", 0,
                                        f"Resume the interview for {name!r} where it "
                                        f"stopped ({len(answers)} of 12 answered)?",
                                        "yes_no", default=True))
        if not resume:
            answers = {}
            discard_progress(name)

    current_round = 0
    for question in QUESTIONS:
        if question.key in answers:
            continue
        if question.round != current_round:
            current_round = question.round
            prompter.say(f"\nRound {current_round} of 4 — {ROUND_TITLES[current_round]}")
        answers[question.key] = ask_one(prompter, question, answers, new_brand)
        save_progress(name, answers)
    return answers


def ask_one(prompter: Prompter, question: Question, answers: Mapping[str, Any],
            new_brand: Callable[[Prompter], str | None] | None = None) -> Any:
    """One question, with the pickers and defaults that depend on earlier answers."""
    if question.key == "profile":
        return ask(prompter, question, profile_choices())
    if question.key == "brand":
        default = "none" if answers.get("profile") == "python-packaged" else None
        while True:
            value = ask(prompter, question, brand_choices(), default=default)
            if value != NEW_BRAND:
                return value
            if new_brand is None:
                prompter.say("  A new brand cannot be created from here; choose one.")
                continue
            slug = new_brand(prompter)
            if slug:
                return slug
            prompter.say("  No brand was created; choose again.")
    return ask(prompter, question)


def edit(name: str, prompter: Prompter, answers: Answers, number: int,
         new_brand: Callable[[Prompter], str | None] | None = None) -> Answers:
    """Re-ask one question by its number, keeping every other answer."""
    if not 1 <= number <= len(QUESTIONS):
        raise ConfigError(f"There is no question {number}; they run from 1 to 12.")
    question = QUESTIONS[number - 1]
    answers[question.key] = ask_one(prompter, question, answers, new_brand)
    save_progress(name, answers)
    return answers


# --- the answers file (spec 11.3) --------------------------------------------

def load_progress(name: str) -> Answers:
    path = paths.onboarding(name)
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    known = {question.key for question in QUESTIONS}
    return {key: value for key, value in data.items() if key in known}


def save_progress(name: str, answers: Mapping[str, Any]) -> None:
    locking.atomic_write_text(
        paths.onboarding(name),
        yaml.safe_dump(dict(answers), allow_unicode=True, sort_keys=False),
    )


def discard_progress(name: str) -> None:
    paths.onboarding(name).unlink(missing_ok=True)
    paths.onboarding_brief(name).unlink(missing_ok=True)


# --- the brief (spec 11.1) ---------------------------------------------------

USERS = {"solo": "You alone", "team": "A team with roles", "public": "The public"}
DEPLOY = {"local": "This machine only", "docker": "A server, Docker Compose behind Caddy"}


def brief_rows(answers: Mapping[str, Any]) -> list[tuple[int, str, str]]:
    """(question number, label, answer) — shared by the page and the terminal."""
    def yes(value: Any) -> str:
        return "yes" if value else "no"

    return [
        (1, "What it is", answers["what_it_does"]),
        (2, "What it is not", answers["what_it_is_not"]),
        (3, "Must never break", answers["must_never_break"]),
        (4, "Who uses it", USERS[answers["users"]]),
        (5, "Reached from", answers["reach"]),
        (6, "Used on a phone", yes(answers["phone"])),
        (7, "Stores", answers["stores"]),
        (8, "Money, personal data or credentials", yes(answers["sensitive_data"])),
        (9, "Profile", answers["profile"]),
        (10, "Brand", answers["brand"]),
        (11, "Deploys to", DEPLOY[answers["deploy"]]),
        (12, "First pieces of work", "; ".join(answers["first_version"])),
    ]


def brief_text(name: str, answers: Mapping[str, Any]) -> str:
    lines = [f"Project brief: {name}", ""]
    for number, label, value in brief_rows(answers):
        lines.append(f"  {NUMERALS[number - 1]} {label}: {value}")
    return "\n".join(lines)


def render_brief(name: str, answers: Mapping[str, Any]) -> str:
    """One standalone page. Every answer escaped; nothing loaded from the network."""
    esc = html.escape
    rows = "\n".join(
        f"<tr><th>{NUMERALS[number - 1]} {esc(label)}</th><td>{esc(str(value))}</td></tr>"
        for number, label, value in brief_rows(answers) if number != 12
    )
    work = "\n".join(f"<li>{esc(item)}</li>" for item in answers["first_version"])

    swatch = "<p>No brand.</p>"
    brand = answers.get("brand")
    if brand and brand != "none":
        tokens_path = paths.brands() / brand / "tokens.css"
        tokens = (brands.tokens_in(tokens_path.read_text(encoding="utf-8"))
                  if tokens_path.is_file() else {})
        chips = "".join(
            f'<figure><div class="chip" style="background:{esc(value)}"></div>'
            f"<figcaption><code>{esc(token)}</code><br>{esc(value)}</figcaption></figure>"
            for token, value in tokens.items() if brands._looks_like_colour(value)
        )
        fonts = "".join(
            f'<p style="font-family:{esc(value)}"><code>{esc(token)}</code> '
            f"The quick brown fox jumps over the lazy dog.</p>"
            for token, value in tokens.items() if token.startswith("--font")
        )
        swatch = f"<p><code>{esc(brand)}</code></p>{chips}{fonts}"

    return "\n".join([
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Brief: {esc(name)}</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:48rem;"
        "padding:0 1rem;color:#222;line-height:1.5}",
        "th{text-align:left;vertical-align:top;padding:.4rem 1rem .4rem 0;width:16rem}",
        "td{padding:.4rem 0}",
        "figure{display:inline-block;margin:0 1rem 1rem 0;text-align:center}",
        ".chip{width:6rem;height:4rem;border:1px solid #ccc;border-radius:6px}",
        "</style></head><body>",
        f"<h1>{esc(name)}</h1>",
        "<p>Nothing has been created yet. Approve, edit an answer, or cancel in the "
        "terminal.</p>",
        f"<table>{rows}</table>",
        "<h2>⑫ The first pieces of work</h2>",
        f"<ol>{work}</ol>",
        "<h2>Brand</h2>",
        swatch,
        "</body></html>",
        "",
    ])


def write_brief(name: str, answers: Mapping[str, Any]) -> Path:
    """Beside the answers file, outside every project (spec 11.1)."""
    page = paths.onboarding_brief(name)
    locking.atomic_write_text(page, render_brief(name, answers))
    return page
