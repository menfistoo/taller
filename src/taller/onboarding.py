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
import textwrap
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
ROUND_TITLES = {1: "what it is for", 2: "who uses it, and from where",
                3: "what it keeps", 4: "how it is built"}
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
    example: str = ""         # an answer someone might give, shown under the question

    @property
    def number(self) -> str:
        """① … ⑫ for the twelve; nothing for a question outside the list."""
        digits = self.id[1:]
        return NUMERALS[int(digits) - 1] if self.id[:1] == "q" and digits.isdigit() else ""


# Plain words first, an example answer under each, and the reason only where it
# changes what someone would answer. Written after the first real use, where the
# owner could not tell what most of the earlier, shorter questions wanted.
QUESTIONS: tuple[Question, ...] = (
    Question("q1", "what_it_does", 1, "What does it do? One sentence is enough.", "text",
             example="Keeps track of which neighbour has borrowed which tool."),
    Question("q2", "what_it_is_not", 1,
             "What should it never turn into? Something you would say no to, even if "
             "someone asked for it.", "text",
             why="Projects tend to grow into something else a little at a time. Writing "
                 "the limit down now lets Taller say no for you later.",
             example="It will never take payments."),
    Question("q3", "must_never_break", 1,
             "What would be a disaster if it stopped working?", "text",
             why="This gets the most careful checking on every change.",
             example="Knowing who has which tool right now."),
    Question("q4", "users", 2, "Who will use it?", "choice",
             why="Hard to change later, because it decides whether people need to sign in.",
             choices=(("solo", "only me"),
                      ("team", "a group of people, some allowed to do more than others"),
                      ("public", "anyone, open to the public"))),
    Question("q5", "reach", 2, "Where will people open it from?", "choice",
             choices=(("this machine", "only this computer"),
                      ("a private network", "inside one building or office network"),
                      ("a VPN", "from outside, through a private connection (VPN)"),
                      ("the internet", "from anywhere, over the internet")),
             default="this machine"),
    Question("q6", "phone", 2, "Will people use it on a phone?", "yes_no", default=False,
             why="If yes, every screen is checked on a small display too."),
    Question("q7", "stores", 3, "What information does it keep?", "text",
             example="The tools, the neighbours, and who borrowed what, and when."),
    Question("q8", "sensitive_data", 3,
             "Does it keep money, payments, personal details (names, emails, phone "
             "numbers) or passwords?", "yes_no",
             why="If yes, every change touching them gets an extra security review, and "
                 "the project keeps a log of who changed what."),
    Question("q9", "profile", 4, "What kind of project is it?", "choice",
             why="This picks the building blocks. If unsure, the web app fits most "
                 "things."),
    Question("q10", "brand", 4, "Which look - colours and fonts - should it use?", "choice",
             why="Choose none for a quick test; a brand can be made later."),
    Question("q11", "deploy", 4, "Where will it run?", "choice",
             choices=(("local", "only on this computer"),
                      ("docker", "on a server, so it can be reached online")),
             default="local"),
    Question("q12", "first_version", 4,
             "What is the smallest version that would already be useful to you?", "list",
             why="List its first pieces of work, one per line. Three to five is about "
                 "right. Press Enter on an empty line when done.",
             example="A page listing my tools / A form to record a loan / "
                     "A page showing who has what"),
)
BY_ID = {question.id: question for question in QUESTIONS}


# --- pickers (spec 4.7: never a typed slug) ----------------------------------

def profile_choices() -> list[Choice]:
    """The hub's profiles first, then what the catalogue offers."""
    hub = catalogue.installed_profiles()
    offered = [name for name in catalogue.list_profiles() if name not in hub]
    def label(name: str, source: dict) -> str:
        return f"{source.get('description') or name}  [{name}]"

    return ([(name, label(name, catalogue.read_hub_profile(name))) for name in hub]
            + [(name, label(name, catalogue.read_profile(name))) for name in offered])


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
    if options and default is not None and default not in [value for value, _ in options]:
        default = None                  # a stale default must not crash the picker
    prompt = _prompt(question, options, default)

    while True:
        if question.kind == "list":
            items = [flatten(line) for line in prompter.ask_lines(question.id, prompt)]
            items = [item for item in items if item]
            if items:
                return items
            if default:
                return list(default)
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
    lines = [textwrap.fill(question.text, width=68, subsequent_indent="     ",
                           initial_indent="  " + (f"{question.number} " if question.number
                                                  else ""))]
    if question.why:
        lines.append(textwrap.fill(f"({question.why})", width=64,
                                   initial_indent="     ", subsequent_indent="      "))
    if question.example:
        lines.append(textwrap.fill(f"For example: {question.example}", width=64,
                                   initial_indent="     ", subsequent_indent="       "))
    # One choice per line: side by side they wrap badly in a narrow terminal.
    lines += [f"     {n}) {label}" for n, (_, label) in enumerate(options, 1)]
    if question.kind == "yes_no":
        lines.append("     [Y/n]" if default is True else "     [y/N]" if default is False
                     else "     [y/n]")
    elif default is not None and options:
        index = next(n for n, (value, _) in enumerate(options, 1) if value == default)
        lines.append(f"     [{index}]")
    elif question.kind == "text" and default:
        lines.append(f"     [{default}]")
    elif question.kind == "list" and default:
        lines.append("     [" + "; ".join(default) + "]  (Enter keeps these)")
    return "\n".join(lines)


# --- the interview -----------------------------------------------------------

def run(name: str, prompter: Prompter, *,
        new_brand: Callable[[Prompter], str | None] | None = None,
        presets: Mapping[str, Any] | None = None,
        extra_brands: tuple[Choice, ...] = ()) -> Answers:
    """All twelve, resuming from the answers file when there is one.

    `presets` are inferred answers (adoption, spec 11.2): still asked, with the
    inference as the default, so a fact is shown for correction rather than
    requested. `extra_brands` lead the brand picker - adoption's "lift these
    tokens" option.
    """
    presets = presets or {}
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
        answers[question.key] = ask_one(prompter, question, answers, new_brand,
                                        current=presets.get(question.key),
                                        extra_brands=extra_brands)
        save_progress(name, answers)
    return answers


def ask_one(prompter: Prompter, question: Question, answers: Mapping[str, Any],
            new_brand: Callable[[Prompter], str | None] | None = None, *,
            current: Any = None, extra_brands: tuple[Choice, ...] = ()) -> Any:
    """One question, with the pickers and defaults that depend on earlier answers.

    `current` is the answer to keep on Enter: an inference, or the answer being
    edited.
    """
    if question.key == "profile":
        return ask(prompter, question, profile_choices(), default=current)
    if question.key == "brand":
        default = current
        if default is None and answers.get("profile") == "python-packaged":
            default = "none"
        choices = [*extra_brands, *brand_choices()]
        while True:
            value = ask(prompter, question, choices, default=default)
            if value != NEW_BRAND:
                return value
            if new_brand is None:
                prompter.say("  A new brand cannot be created from here; choose one.")
                continue
            slug = new_brand(prompter)
            if slug:
                return slug
            prompter.say("  No brand was created; choose again.")
    return ask(prompter, question, default=current)


def edit(name: str, prompter: Prompter, answers: Answers, number: int,
         new_brand: Callable[[Prompter], str | None] | None = None) -> Answers:
    """Re-ask one question by its number, keeping every other answer."""
    if not 1 <= number <= len(QUESTIONS):
        raise ConfigError(f"There is no question {number}; they run from 1 to 12.")
    question = QUESTIONS[number - 1]
    answers[question.key] = ask_one(prompter, question, answers, new_brand,
                                    current=answers.get(question.key))
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
    paths.onboarding(name).with_suffix(".distilled.json").unlink(missing_ok=True)


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


def brief_text(name: str, answers: Mapping[str, Any], notes: tuple[str, ...] = ()) -> str:
    lines = [f"Project brief: {name}", ""]
    for number, label, value in brief_rows(answers):
        lines.append(f"  {NUMERALS[number - 1]} {label}: {value}")
    if notes:
        lines += ["", "  What else changes:"] + [f"    - {note}" for note in notes]
    return "\n".join(lines)


def render_brief(name: str, answers: Mapping[str, Any], notes: tuple[str, ...] = (),
                 tokens: Mapping[str, str] | None = None) -> str:
    """One standalone page. Every answer escaped; nothing loaded from the network.

    `notes` list what else the approval will change (adoption's lifts); `tokens`
    shows a palette that is not in the hub yet.
    """
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
        if tokens is None:
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
        *(["<h2>What else changes</h2>", "<ul>",
           *(f"<li>{esc(note)}</li>" for note in notes), "</ul>"] if notes else []),
        "</body></html>",
        "",
    ])


def write_brief(name: str, answers: Mapping[str, Any], notes: tuple[str, ...] = (),
                tokens: Mapping[str, str] | None = None) -> Path:
    """Beside the answers file, outside every project (spec 11.1)."""
    page = paths.onboarding_brief(name)
    locking.atomic_write_text(page, render_brief(name, answers, notes, tokens))
    return page
