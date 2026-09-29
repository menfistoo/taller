"""Scaffolds, and creating a project from one.

Spec 11.4. A scaffold is a template directory plus a `manifest.yml` — not
generated code — so it is auditable, and editable without touching Python. The
manifest says, per file, whether it is copied or substituted, and which answers
omit it: a scaffold is shaped by the answers, not pasted whole.

**Why `%%key%%` and not Jinja.** A Flask scaffold's templates *are* Jinja, and
`{{ url_for(...) }}` must reach the project untouched. A marker Jinja never uses
avoids escaping every template.

`create_project` is the library half of `taller project new`. The command asks
the twelve questions and gets the brief approved; this validates everything
before writing anything, builds the project in a staging directory, commits it,
and only then moves it into place and registers it.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import yaml

from . import brands, catalogue, config, generated, gitio, hub, paths, registry
from .errors import ConfigError

# The facts a manifest may test, with their values. Closed on purpose: a typo in
# a manifest would otherwise omit a file silently, for ever.
FACTS: dict[str, tuple[str, ...]] = {
    "users": ("solo", "team", "public"),           # answer 4
    "deploy": ("local", "docker"),                 # answer 11
    "sensitive_data": ("yes", "no"),               # answer 8
    "phone": ("yes", "no"),                        # answer 6
    "brand": ("none", "set"),                      # answer 10
}
VARIABLES = ("name", "package", "description", "ui_lang", "taller_source")
CI_WORKFLOW = ".github/workflows/taller-ci.yml"
# What the install step runs when `ci.taller_source` is unset: stop, and say what
# to set. NEVER `pip install taller` - Taller is not on PyPI, so a bare name would
# fetch whatever stranger has registered it and run its build in her CI runner.
UNSET_INSTALL = (
    'echo "Taller is not configured for CI: set the address to install it from with'
    " \`taller settings set ci.taller_source '<pip requirement>'\`,"
    ' then commit the workflow this rewrites." >&2; exit 1')
ENTRY_KEYS = {"path", "source", "substitute", "omit_when", "only_when"}
_MARKER = re.compile(r"%%([A-Za-z_]+)%%")

# The twelve answers `create_project` needs; 9 and 10 arrive as `profile` and
# `brand`. Text answers are flattened to one line before they reach a file.
TEXT_ANSWERS = ("what_it_does", "what_it_is_not", "must_never_break", "reach", "stores")
REQUIRED_ANSWERS = TEXT_ANSWERS + ("users", "phone", "sensitive_data", "deploy",
                                   "first_version")

# The product summary is the one line of `product.md` the index carries (3.1).
# Capped, so no answer can push the index past its 600-token budget.
SUMMARY_MAX = 120

USERS_LABEL = {
    "solo": "One operator: the owner alone.",
    "team": "A team with roles.",
    "public": "The public.",
}
DEPLOY_LABEL = {
    "local": "This machine only.",
    "docker": "A server, with Docker Compose behind Caddy.",
}


@dataclass
class CreateReport:
    path: Path
    sync: str
    files: list[str] = field(default_factory=list)
    profile_installed: catalogue.InstallReport | None = None


# --- render ------------------------------------------------------------------

def configured_taller_source() -> str:
    """`ci.taller_source` from the hub. Empty when she has not set it (spec 9.4)."""
    ci = config.load_hub_config().get("ci") or {}
    return str(ci.get("taller_source") or "")


def ci_template() -> Path:
    return paths.catalogue() / "ci" / "taller-ci.yml"


def ci_workflow(taller_source: str) -> bytes:
    """The one CI workflow every project gets, with the install step filled in.

    One template for all profiles: the workflow runs `taller ci`, which is the
    same three gates whatever the project is made of. An unset address yields a
    step that stops with what to set, never an install of something else.
    """
    install = (f'pip install "{taller_source}"' if taller_source.strip()
               else UNSET_INSTALL)
    text = ci_template().read_text(encoding="utf-8").replace("%%install_taller%%", install)
    return text.encode("utf-8")


def render(profile: str, *, name: str, description: str,
           facts: Mapping[str, str], ui_lang: str,
           taller_source: str = "") -> dict[str, bytes]:
    """Every file the profile's scaffold yields for these facts. Pure."""
    folder = paths.catalogue() / "scaffolds" / profile
    manifest_path = folder / "manifest.yml"
    if not manifest_path.is_file():
        raise ConfigError(f"The catalogue has no scaffold for profile {profile!r}.")
    _check_facts(facts, "the facts given to render()")

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ConfigError(f"{manifest_path}: `files` must be a list.")

    variables = {
        "name": name,
        "package": name.replace("-", "_"),
        "description": description,
        "ui_lang": ui_lang,
        "taller_source": taller_source,
    }
    # Every project gets the same CI workflow, whatever it is made of: the checks
    # it runs are `taller ci`, not anything profile-specific (spec 9.4). A
    # catalogue without the template - a test's fake one - simply yields no
    # workflow; that the shipped catalogue has it is asserted on its own.
    out: dict[str, bytes] = ({CI_WORKFLOW: ci_workflow(taller_source)}
                             if ci_template().is_file() else {})
    for entry in entries:
        destination = _entry_path(entry, manifest_path)
        if not _included(entry, facts, manifest_path):
            continue
        if destination in out:
            raise ConfigError(
                f"{manifest_path}: {destination} is produced twice for these answers. "
                f"Two entries for one path need conditions that exclude each other."
            )
        source = folder / str(entry.get("source") or destination)
        if not source.resolve().is_relative_to(folder.resolve()) or not source.is_file():
            raise ConfigError(f"{manifest_path}: the source for {destination} "
                              f"({entry.get('source') or destination}) does not exist.")
        data = source.read_bytes()
        if entry.get("substitute"):
            data = _substitute(data.decode("utf-8"), variables, source).encode("utf-8")
        out[destination] = _lf(data)
    return out


def _entry_path(entry: Any, manifest: Path) -> str:
    if not isinstance(entry, dict) or "path" not in entry:
        raise ConfigError(f"{manifest}: every entry is a mapping with a `path`; got {entry!r}.")
    unknown = set(entry) - ENTRY_KEYS
    if unknown:
        raise ConfigError(f"{manifest}: unknown keys {sorted(unknown)} in {entry!r}.")
    raw = str(entry["path"])
    pure = PurePosixPath(raw)
    if pure.is_absolute() or ".." in pure.parts or "\\" in raw or not raw:
        raise ConfigError(
            f"{manifest}: {raw!r} would escape the project; paths are relative "
            f"and POSIX."
        )
    return pure.as_posix()


def _included(entry: dict, facts: Mapping[str, str], manifest: Path) -> bool:
    omit = entry.get("omit_when") or {}
    only = entry.get("only_when") or {}
    for label, condition in (("omit_when", omit), ("only_when", only)):
        _check_condition(condition, f"{manifest}: {label} of {entry['path']}")
    if any(facts[key] in values for key, values in omit.items()):
        return False
    return all(facts[key] in values for key, values in only.items())


def _check_condition(condition: Any, where: str) -> None:
    if not isinstance(condition, dict):
        raise ConfigError(f"{where} must map facts to lists of values.")
    for key, values in condition.items():
        if key not in FACTS:
            raise ConfigError(f"{where} tests {key!r}, which is not one of the facts "
                              f"{sorted(FACTS)}.")
        if not isinstance(values, list):
            raise ConfigError(f"{where}: the values for {key!r} must be a list.")
        bad = [value for value in values if value not in FACTS[key]]
        if bad:
            raise ConfigError(f"{where}: {bad} are not values of {key!r}; it takes "
                              f"{list(FACTS[key])}.")


def _check_facts(facts: Mapping[str, str], where: str) -> None:
    for key, allowed in FACTS.items():
        if facts.get(key) not in allowed:
            raise ConfigError(f"{where}: {key!r} must be one of {list(allowed)}; "
                              f"got {facts.get(key)!r}.")


def _substitute(text: str, variables: Mapping[str, str], source: Path) -> str:
    """One pass, so a substituted value is never itself substituted."""
    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in variables:
            raise ConfigError(f"{source} uses %%{key}%%, which is not one of "
                              f"{list(VARIABLES)}.")
        return variables[key]
    return _MARKER.sub(replace, text)


def _lf(data: bytes) -> bytes:
    """Text to LF, whatever a checkout did to the template. Binary untouched."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    return text.replace("\r\n", "\n").encode("utf-8")


# --- .gitattributes ----------------------------------------------------------

def render_gitattributes(brand_tokens: str | None) -> bytes:
    """The project's `.gitattributes`: LF everywhere, `merge=ours` on generated files.

    Not optional (spec 11.4): with `core.autocrlf=true` git hands a generated file
    back as CRLF, and the byte-for-byte tamper check (4.6) fires on a clean
    checkout. The generated files are regenerated rather than merged, so the
    `ours` driver keeps a conflict from ever arising. `adopt` writes the same.
    """
    generated = [".taller/resolved.json", ".taller/constitution/00-index.md"]
    if brand_tokens:
        generated.append(brand_tokens)
    lines = [
        "# Written by Taller. Line endings are LF so generated files compare",
        "# byte for byte on every platform.",
        "* text=auto eol=lf",
        "",
        "# Generated: regenerated, never merged.",
        *(f"{path} text eol=lf merge=ours" for path in generated),
        "",
        "*.png binary",
        "*.jpg binary",
        "*.jpeg binary",
        "*.gif binary",
        "*.ico binary",
        "*.pdf binary",
        "*.woff binary",
        "*.woff2 binary",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


# --- create_project ----------------------------------------------------------

def create_project(target: Path | str, *, name: str, profile: str,
                   brand: str | None, answers: Mapping[str, Any]) -> CreateReport:
    """Create, commit and register a project from the twelve answers (spec 11.4)."""
    target = Path(target)

    # 1. Validate everything before writing anything.
    if not isinstance(name, str) or not brands.SLUG.match(name):
        raise ConfigError(
            f"{name!r} is not a usable project name: lowercase letters, digits and "
            f"hyphens, starting with a letter or digit."
        )
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ConfigError(f"{target} exists and is not empty. A new project needs an "
                          f"empty directory; `taller project adopt` takes an existing one.")
    if profile not in set(catalogue.list_profiles()) | set(catalogue.installed_profiles()):
        raise ConfigError(f"There is no profile {profile!r} in the hub or the "
                          f"catalogue. The catalogue offers: "
                          f"{', '.join(catalogue.list_profiles())}.")
    brand_slug = None if brand in (None, "none") else brand
    if brand_slug is not None and brand_slug not in brands.list_brands():
        raise ConfigError(f"The hub has no brand {brand_slug!r}. Create it with "
                          f"`taller brand new`, or choose none.")
    language = config.load_hub_config().get("language")
    if not isinstance(language, dict) or not language.get("code"):
        raise ConfigError(
            "The hub's `language` is not set, and a project must never be created "
            "without it: the UI-language rules guard on it and would silently do "
            "nothing (spec 11.1). Run `taller setup` first."
        )
    clean = validate_answers(answers)
    facts = {
        "users": clean["users"],
        "deploy": clean["deploy"],
        "sensitive_data": clean["sensitive_data"],
        "phone": clean["phone"],
        "brand": "set" if brand_slug else "none",
    }
    ui = language.get("ui")
    ui_lang = str(ui if ui and ui != "none" else language["code"])
    rendered = render(profile, name=name, description=clean["what_it_does"],
                      facts=facts, ui_lang=ui_lang,
                      taller_source=configured_taller_source())

    # 2. The hub gets the profile if it lacks it - atomic with its modules (4.0).
    installed = None
    if profile not in catalogue.installed_profiles():
        installed = catalogue.install_profile(profile)
        # Committed before anything is resolved: the snapshot records the hub's
        # HEAD, and a hub commit after it would mark it stale at birth (4.6).
        hub.commit(f"profile: add {profile}")
    brand_tokens = catalogue.read_hub_profile(profile).get("paths", {}).get("brand_tokens")

    # 3-4. Build and commit in a staging directory, then move it into place, so
    # a failure half way leaves nothing where the project was meant to be.
    files = dict(rendered)
    files[".gitattributes"] = render_gitattributes(brand_tokens if brand_slug else None)
    files.update(taller_files(name, clean, profile=profile, brand=brand_slug))
    staging = target.parent / f".{target.name}.taller-staging"
    if staging.exists():
        shutil.rmtree(staging)                     # ours, from an interrupted run
    try:
        for relative, data in files.items():
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        gitio.git(staging, "init", "--quiet", "-b", gitio.MAIN_BRANCH)
        gitio.git(staging, "config", "merge.ours.driver", "true")
        gitio.git(staging, "add", "--all")
        gitio.git(staging, "commit", "--quiet", "-m",
                  f"Create {name} from the {profile} scaffold")
        if target.exists():
            target.rmdir()                          # empty, checked above
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # 5. Register, then write the generated files through the only writer.
    registry.add_project(path=target, name=name, profile=profile, brand=brand_slug)
    gitio.ensure_main_worktree(target)
    written = generated.render_all(target)
    sync = gitio.commit_to_main(target, written, "taller: resolve the constitution")

    return CreateReport(path=target.resolve(), sync=sync,
                        files=sorted([*files, *written]), profile_installed=installed)


def validate_answers(answers: Mapping[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED_ANSWERS if key not in answers]
    if missing:
        raise ConfigError(f"Onboarding answers are missing: {', '.join(missing)}.")
    clean: dict[str, Any] = {}
    for key in TEXT_ANSWERS:
        clean[key] = flatten(answers[key])
        if not clean[key]:
            raise ConfigError(f"The answer {key!r} is empty.")
    for key in ("users", "deploy"):
        if answers[key] not in FACTS[key]:
            raise ConfigError(f"The answer {key!r} must be one of {list(FACTS[key])}; "
                              f"got {answers[key]!r}.")
        clean[key] = answers[key]
    for key in ("phone", "sensitive_data"):
        clean[key] = _yes_no(answers[key], key)
    first = answers["first_version"]
    if not isinstance(first, list) or not [item for item in first if flatten(item)]:
        raise ConfigError("The answer 'first_version' must list at least one piece of work.")
    clean["first_version"] = [flatten(item) for item in first if flatten(item)]
    return clean


def _yes_no(value: Any, key: str) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value in ("yes", "no"):
        return value
    raise ConfigError(f"The answer {key!r} must be yes or no; got {value!r}.")


def flatten(value: Any) -> str:
    """One line, with no leading `>`.

    Every answer lands at the start of a line in a slice file, and the index
    collects every line starting `> ` (3.1): an answer must not be able to add
    a summary of its own.
    """
    text = " ".join(str(value).split())
    return re.sub(r"^(?:>\s*)+", "", text)


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


PRODUCT_MD = ".taller/constitution/product.md"
NEVER_MD = ".taller/constitution/never.md"
OVERRIDES_MD = ".taller/constitution/overrides.md"
ARCHITECTURE_MD = ".taller/constitution/architecture.md"
QUEUE_YML = ".taller/queue.yml"
BRIEF_YML = ".taller/brief.yml"
PROJECT_CONFIG = ".taller/taller.yml"


def product_md(name: str, answers: Mapping[str, Any]) -> bytes:
    """The product slice, from answers 1, 3-8 and 11. Validated answers only."""
    return "\n".join([
        f"> {_cap(answers['what_it_does'], SUMMARY_MAX)}",
        "",
        f"# {name}",
        "",
        answers["what_it_does"],
        "",
        "## Must never break",
        "",
        answers["must_never_break"],
        "",
        "## Who uses it, and from where",
        "",
        USERS_LABEL[answers["users"]],
        "",
        f"Reached from: {answers['reach']}. Used on a phone: {answers['phone']}.",
        "",
        "## Data",
        "",
        answers["stores"],
        "",
        f"Money, personal data or credentials: {answers['sensitive_data']}.",
        "",
        "## Deploys to",
        "",
        DEPLOY_LABEL[answers["deploy"]],
        "",
    ]).encode("utf-8")


def never_md(answers: Mapping[str, Any]) -> bytes:
    """The project's own prohibitions, appended to the hub's (answer 2)."""
    return "\n".join([
        "## This project",
        "",
        "It deliberately does not do the following. Work that would make it do so",
        "is out of scope, whatever the ticket says.",
        "",
        f"- {answers['what_it_is_not']}",
        "",
    ]).encode("utf-8")


def queue_yml(answers: Mapping[str, Any]) -> bytes:
    return (
        "# The smallest useful version, in the owner's words (onboarding answer 12).\n"
        "# `taller ticket new --from-queue` turns each entry into a ticket.\n"
        + yaml.safe_dump(
            {"proposed": [{"title": title} for title in answers["first_version"]]},
            allow_unicode=True, sort_keys=False,
        )
    ).encode("utf-8")


def brief_yml(answers: Mapping[str, Any], *, profile: str, brand: str | None) -> bytes:
    """The twelve answers, kept so `taller project brief` can reopen them (11.1.1).

    Stored in the shape the interview produces, so reopening is a plain load.
    Not a slice: never loaded into a session's context.
    """
    record = {key: answers[key] for key in TEXT_ANSWERS}
    record.update({
        "users": answers["users"],
        "phone": answers["phone"] == "yes",
        "sensitive_data": answers["sensitive_data"] == "yes",
        "deploy": answers["deploy"],
        "first_version": list(answers["first_version"]),
        "profile": profile,
        "brand": brand or "none",
    })
    return (
        "# The onboarding answers. `taller project brief` edits them; hand edits are\n"
        "# fine, and are read the next time the brief is opened.\n"
        + yaml.safe_dump(record, allow_unicode=True, sort_keys=False)
    ).encode("utf-8")


def load_brief(project: Path | str) -> dict[str, Any]:
    path = Path(project) / BRIEF_YML
    if not path.is_file():
        raise ConfigError(f"{project} has no {BRIEF_YML}. It was not created or adopted "
                          f"by Taller, so there are no answers to reopen.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping.")
    return data


def overrides_md() -> bytes:
    return "\n".join([
        "---",
        "overrides: []",
        "---",
        "",
        "Record a deliberate deviation from a rule here, with a reason and, if it",
        "is temporary, an `until` date. A deviation with no reason is reported.",
        "",
    ]).encode("utf-8")


def claude_md(name: str) -> bytes:
    """The stub every Taller project gets: the index is the only preamble."""
    return "\n".join([
        f"# {name}",
        "",
        "This project is run with Taller. Read `.taller/constitution/00-index.md`",
        "first: it says which part of the constitution a task needs, so load only",
        "that.",
        "",
    ]).encode("utf-8")


def taller_files(name: str, answers: Mapping[str, Any], *, profile: str,
                 brand: str | None) -> dict[str, bytes]:
    """What every project gets whatever its profile (spec 11.4)."""
    return {
        PROJECT_CONFIG: b"",                         # no deviations yet (spec 5)
        PRODUCT_MD: product_md(name, answers),
        NEVER_MD: never_md(answers),
        OVERRIDES_MD: overrides_md(),
        QUEUE_YML: queue_yml(answers),
        BRIEF_YML: brief_yml(answers, profile=profile, brand=brand),
        "CLAUDE.md": claude_md(name),
    }
