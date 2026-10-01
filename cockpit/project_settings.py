"""A project's settings, in her words: about it, its rules, its look, its choices.

Each tab reads through the same library the terminal uses and writes through it
too - an answer changed here is `scaffold.amend_brief`, exactly as
`taller project brief` writes it, and a rule added here is `own_rules.add`.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Mapping

import re
import uuid

from taller import (brands, catalogue, generated, hub, onboarding, overrides, own_rules, paths,
                    prompter, registry, scaffold, settings, tickets)
from taller.errors import ConfigError, TallerError

from . import plain, reading, words

# The five cards of "About it", each with the answers it shows and changes. The
# profile, the brand and where it runs are not here: the first two change what
# the project is built from, and are not an answer to edit.
CARDS = (
    ("what", ("what_it_does",)),
    ("disaster", ("must_never_break",)),
    ("never", ("what_it_is_not",)),
    ("keeps", ("stores", "sensitive_data")),
    ("who", ("users", "reach", "phone")),
)
EDITABLE = frozenset(key for _, keys in CARDS for key in keys)


def about(project_name: str) -> dict[str, Any]:
    """The answers as five cards, each said the way she would say it."""
    entry = reading.entry_for(project_name)
    answers = scaffold.load_brief(Path(entry["path"]))
    cards = []
    for card, keys in CARDS:
        cards.append({
            "card": card,
            "title": words.ABOUT["cards"][card],
            "said": _said(card, answers),
            "note": words.ABOUT["sensitive"] if card == "keeps" and answers.get("sensitive_data")
            else "",
            "fields": [_field(key, answers) for key in keys],
        })
    return {"project": entry["name"], "cards": cards}


def change_answers(project_name: str, given: Mapping[str, Any]) -> dict[str, Any]:
    """Change one card's answers as one amendment. `{"ok", "problem", "lines"}`.

    Every answer is judged by `onboarding.ask_one` with an answer sheet - the call
    the interview makes - before anything is written, so a refusal changes nothing.
    """
    entry = reading.entry_for(project_name)
    path = Path(entry["path"])
    answers = scaffold.load_brief(path)
    changed = []
    for key, raw in given.items():
        if key not in EDITABLE:
            continue
        question = next(q for q in onboarding.QUESTIONS if q.key == key)
        sheet = prompter.AnswerSheetPrompter({question.id: raw})
        try:
            value = onboarding.ask_one(sheet, question, answers)
        except prompter.NeedsAnswer:
            return {"ok": False, "problem": _refusal(question), "lines": []}
        if value != answers.get(key):
            answers[key] = value
            changed.append(key)
    if not changed:
        return {"ok": True, "problem": "", "lines": [words.ABOUT["unchanged"]]}
    try:
        scaffold.amend_brief(path, entry["name"], answers, changed)
    except TallerError as exc:
        return {"ok": False, "problem": plain.problem(exc), "lines": []}
    return {"ok": True, "problem": "", "lines": [words.ABOUT["changed"]]}


def change_answer(project_name: str, key: str, raw: str | list[str]) -> dict[str, Any]:
    """One answer: `change_answers` with a single key."""
    return change_answers(project_name, {key: raw})


def _field(key: str, answers: Mapping[str, Any]) -> dict[str, Any]:
    question = next(q for q in onboarding.QUESTIONS if q.key == key)
    return {"key": key, "label": question.text, "kind": question.kind,
            "choices": list(question.choices), "value": answers.get(key)}


def _said(card: str, answers: Mapping[str, Any]) -> str:
    if card == "keeps":
        return str(answers.get("stores") or "")
    if card == "who":
        return words.who_uses(answers.get("users"), answers.get("reach"), answers.get("phone"))
    key = dict(CARDS)[card][0]
    return str(answers.get(key) or "")


def _refusal(question: onboarding.Question) -> str:
    if question.kind == "yes_no":
        return "Please answer yes or no."
    if question.choices:
        return "Please choose one of the options."
    return "An answer is needed."




# --- its rules --------------------------------------------------------------------

def rules(project_name: str) -> dict[str, Any]:
    """Her rules, the exceptions she allowed, and Taller's own rules in one line each."""
    entry = reading.entry_for(project_name)
    path = Path(entry["path"])
    mine = own_rules.read(path)
    return {
        "project": entry["name"],
        "always": [{**rule, "added_words": words.on_day(rule["added"]) if rule["added"] else ""}
                   for rule in mine["always"]],
        "never": [{**rule, "added_words": words.on_day(rule["added"]) if rule["added"] else ""}
                  for rule in mine["never"]],
        # Her answer "what it should never turn into" is a never-rule as well; it is
        # shown here so the list is whole, and changed on About it, where it lives.
        "never_from_about": str(scaffold.load_brief(path).get("what_it_is_not") or ""),
        "exceptions": _exceptions(path),
        "practice": _practice(entry.get("profile", "")),
    }


def add_rule(project_name: str, kind: str, text: str, why: str) -> list[str]:
    own_rules.add(Path(reading.entry_for(project_name)["path"]), kind, text, why)
    return [words.RULES["saved"]]


def remove_rule(project_name: str, kind: str, index: int, why: str) -> list[str]:
    """What the library reports is for a terminal; the page says it in her words."""
    own_rules.remove(Path(reading.entry_for(project_name)["path"]), kind, index, why)
    return [words.RULES["saved"]]


def _exceptions(path: Path) -> list[dict[str, Any]]:
    """Each exception in words: what it allows, where, why, and until when."""
    source = paths.project_constitution(path) / "overrides.md"
    if not source.is_file():
        return []
    try:
        listed = overrides.parse(source.read_text(encoding="utf-8"))
    except TallerError:
        return []
    out = []
    for override in listed:
        until = override.get("until")
        ran_out = isinstance(until, date) and until < date.today()
        scope = str(override.get("scope") or "")
        out.append({
            "what": plain.sentence({"rule": override.get("rule", ""), "message": "",
                                    "file": "" if scope in ("", "*") else scope},
                                   place=plain._plain_name),
            "why": str(override.get("reason") or ""),
            "until": words.until_line(until, ran_out) if until else "",
            "ran_out": ran_out,
        })
    return out


def _practice(profile: str) -> list[str]:
    """One plain line for each of Taller's rule files this project follows."""
    try:
        modules = catalogue.read_hub_profile(profile).get("modules") or []
    except TallerError:
        return []
    return [words.PRACTICE.get(module) or _summary_of(module) for module in modules]


def _summary_of(module: str) -> str:
    """The `> ` line a rule file opens with - its own summary, never its name."""
    source = paths.modules() / f"{module}.md"
    try:
        for line in source.read_text(encoding="utf-8").splitlines():
            if line.startswith(">"):
                return line.lstrip("> ").strip()
    except OSError:
        pass
    return "A rule that comes with Taller"


# --- look and feel ----------------------------------------------------------------

UPLOAD_MAX = 20 * 1024 * 1024
UPLOAD_KINDS = (".pdf", ".png", ".jpg", ".jpeg", ".css")
_COLOUR = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgba?\(.*\)|hsla?\(.*\))$")


def look(project_name: str) -> dict[str, Any]:
    """The brand this project uses, as colours and type, and who else uses it."""
    entry = reading.entry_for(project_name)
    slug = entry.get("brand")
    hub_brands = brands.list_brands()
    found = brand_view(slug) if slug in hub_brands else None
    others = [row["name"] for row in registry.list_projects()
              if row.get("brand") == slug and row["name"] != entry["name"]] if found else []
    return {"project": entry["name"], "brand": found, "shared_with": others,
            "choices": [b for b in hub_brands if b != slug], "proposal": None}


def brand_view(slug: str) -> dict[str, Any]:
    """One brand, as she sees it: swatches named in words, typefaces, and its words."""
    folder = paths.brands() / slug
    tokens = brands.tokens_in((folder / "tokens.css").read_text(encoding="utf-8"))
    prose = (folder / "brand.md").read_text(encoding="utf-8") \
        if (folder / "brand.md").is_file() else ""
    return {"slug": slug, **_as_seen(tokens), "prose": _plain_prose(prose)}


def _as_seen(tokens: Mapping[str, str]) -> dict[str, Any]:
    swatches, fonts, other = [], [], []
    for name, value in tokens.items():
        if name.startswith("--font"):
            fonts.append({"field": name, "label": words.FONT_LABELS.get(name, "Other"),
                          "family": value, "name": value.split(",")[0].strip().strip('"\'')})
        elif _COLOUR.match(value.strip()):
            swatches.append({"field": name, "label": words.COLOUR_LABELS.get(name, "Other"),
                             "value": value, "hex": value.strip().startswith("#")
                             and len(value.strip()) == 7})
        else:
            other.append({"field": name, "value": value})
    return {"swatches": swatches, "fonts": fonts, "other": other}


_TOKEN_NAME = re.compile(r"`?(--(?:color|colour|font)-[A-Za-z0-9_-]+)`?")


def _plain_prose(prose: str) -> str:
    """brand.md in her words: without the `> ` marker its first line carries for the
    index, and with colours and typefaces called by their names on the page ("Main")
    rather than the code names a brand description may use ("--color-primary")."""
    lines = prose.strip().splitlines()
    if lines and lines[0].startswith("> "):
        lines[0] = lines[0][2:]
    return _TOKEN_NAME.sub(lambda match: _label_of(match.group(1)), "\n".join(lines).strip())


def _label_of(name: str) -> str:
    known = words.COLOUR_LABELS.get(name) or words.FONT_LABELS.get(name)
    if known:
        return known
    return name.lstrip("-").split("-", 1)[-1].replace("-", " ").capitalize()


def save_brand(slug: str, tokens: Mapping[str, str], prose: str, *, new: bool = False,
               name: str = "") -> list[str]:
    """Change a brand - every project using it follows - or make a new one."""
    if new:
        slug = tickets.slugify(name)[:40].strip("-")
        if not slug:
            raise ConfigError("Give the brand a name first.")
        if slug in brands.list_brands():
            raise ConfigError(f"There is already a brand called {slug}. Choose another name.")
    tokens = {key: value.strip() for key, value in tokens.items() if value.strip()}
    brands.write(slug, tokens, prose, replace=not new)
    hub.commit(f"brand: {'new' if new else 'amend'} {slug}")
    if new:
        return [words.LOOK["made"]]
    generated.refresh_affected(brand=slug, message=f"taller: resolve after brand {slug}")
    return [words.LOOK["saved"]]


def propose_from(upload: Path, filename: str) -> dict[str, Any]:
    """A brand guide read into a proposal she checks. Writes nothing, keeps nothing."""
    suffix = Path(filename).suffix.lower()
    try:
        if suffix not in UPLOAD_KINDS:
            return {"problem": words.LOOK["not_a_guide"]}
        tokens = _read_guide(upload)
    except (TallerError, OSError, ValueError):
        return {"problem": words.LOOK["nothing_found"]}
    finally:
        upload.unlink(missing_ok=True)
    if not tokens:
        return {"problem": words.LOOK["nothing_found"]}
    return {"problem": "", **_as_seen(tokens)}


def _read_guide(path: Path) -> dict[str, str]:
    """The tokens a file suggests: a stylesheet's own, or a PDF's or picture's colours."""
    if path.suffix.lower() == ".css":
        return brands.from_css(path)
    proposal = brands.from_pdf(path) if path.suffix.lower() == ".pdf" else brands.from_image(path)
    return brands.propose_tokens(proposal)


def upload_dir() -> Path:
    """Where a guide waits while it is read - never the hub, never the project."""
    return paths.run_dir() / "cockpit-uploads"


def keep_upload(stream: Any, filename: str) -> Path:
    upload_dir().mkdir(parents=True, exist_ok=True)
    target = upload_dir() / f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
    stream.save(str(target))
    return target


def use_brand(project_name: str, slug: str) -> int:
    """Putting a brand on a project changes its own screens: asked for as work."""
    from . import runs

    if slug not in brands.list_brands():
        raise ConfigError(f"There is no brand called {slug}.")
    entry = reading.entry_for(project_name)
    path = Path(entry["path"])
    ask = (f"Use the {slug} brand for this project: its colours and typefaces on every "
           f"screen, in place of whatever it uses now.")
    made = tickets.create(path, title=f"Use the {slug} brand", words=ask, kind="feature",
                          named_by=None)
    runs.start(path, entry["name"], int(made["id"]))
    return int(made["id"])


# --- choices ------------------------------------------------------------------------

# Each choice: the value every option writes, in the order the page shows them.
# The budget pairs are provisional, like the shipped default they sit around.
_BUDGETS = {"little": (500_000, 1_500_000), "normal": (1_200_000, 4_000_000),
            "a_lot": (3_000_000, 10_000_000)}
CHOICE_KEYS = ("publish", "budget", "tries", "language")


def choices(project_name: str) -> dict[str, Any]:
    """The four choices, each with the option in force - or none, when the value in
    force is one no option would write."""
    entry = reading.entry_for(project_name)
    now = {key: value for key, value, _ in settings.effective(Path(entry["path"]))}
    found = []
    for key in CHOICE_KEYS:
        title, note = words.CHOICES["items"][key]
        options = words.CHOICES["options"][key]
        found.append({"key": key, "title": title, "note": note,
                      "options": list(options.items()), "current": _current(key, now)})
    return {"project": entry["name"], "choices": found}


def _current(key: str, now: Mapping[str, Any]) -> str | None:
    if key == "publish":
        value = now.get("publish.automatic")
        return {True: "on", False: "off"}.get(value) if isinstance(value, bool) else None
    if key == "budget":
        pair = (now.get("budget.per_ticket_warn"), now.get("budget.per_ticket_stop"))
        return next((name for name, values in _BUDGETS.items() if values == pair), None)
    if key == "tries":
        value = now.get("thresholds.max_fix_rounds")
        return str(value) if value in (1, 2, 3) and not isinstance(value, bool) else None
    ui = now.get("language.ui")
    value = ui if ui and ui != "none" else now.get("language.code")
    return value if value in words.CHOICES["options"]["language"] else None


def choose(project_name: str, key: str, value: str) -> list[str]:
    """One option, written to the project's own layer - never the hub."""
    if value not in words.CHOICES["options"].get(key, {}):
        raise ConfigError(words.CHOICES["unknown"])
    path = Path(reading.entry_for(project_name)["path"])
    if key == "publish":
        settings.set_value("publish.automatic", "true" if value == "on" else "false", path)
    elif key == "budget":
        warn, stop = _BUDGETS[value]
        # One write, so the pair lands in one commit and is never half-changed.
        settings.set_value("budget", f"{{per_ticket_warn: {warn}, per_ticket_stop: {stop}}}",
                           path)
    elif key == "tries":
        settings.set_value("thresholds.max_fix_rounds", value, path)
    else:
        settings.set_value("language.ui", value, path)
    return [words.CHOICES["saved"]]
