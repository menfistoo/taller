"""`taller project new`: setup if needed, twelve questions, the brief, the project.

Spec 11.1 and 11.4. Nothing is written into the project or the hub before the
brief is approved — the only file written earlier is the resume file, outside
every project. After approval `scaffold.create_project` does the work; this
module only holds the conversation.
"""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path
from typing import Any

import yaml

from .. import adopt as adopt_lib
from .. import brands, config, discovery, generated, gitio, onboarding, paths, registry, scaffold
from ..errors import ConfigError
from ..onboarding import Question, ask
from ..prompter import Prompter
from . import brand as brand_command
from . import common
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
    if not prompter.interactive:
        # The project exists by now; a question here would stop the command after
        # it had already done its work, and running it again is refused (plugin
        # review, C2). The default is no, so say how to push later instead.
        prompter.say(f"  Not pushed to GitHub. To publish it later: `gh repo create {name} "
                     f"--private --source {target} --remote origin --push`.")
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


# --- taller project brief (spec 11.1.1) ---------------------------------------

# A change of stack or brand is not an answer edit: it changes which rules apply
# and which generated files exist, so it is refused here with the reason.
FIXED_IN_BRIEF = {9: "the profile", 10: "the brand"}


def brief(args: Any, prompter: Prompter) -> int:
    project = common.project_path(args.path)
    entry = registry.get_project(project)
    if not registry.is_adopted(entry):
        raise ConfigError(f"{entry['name']} is registered but not adopted yet: "
                          f"`taller project adopt {project}` first.")
    gitio.require_clean_main(project, "`taller project brief`")
    name = entry["name"]
    answers = scaffold.load_brief(project)
    original = copy.deepcopy(answers)

    while True:
        prompter.say("\n" + onboarding.brief_text(name, answers))
        if not args.no_open:
            brand_command.open_in_browser(onboarding.write_brief(name, answers))
        raw = prompter.ask("brief.edit",
                           "  A question number to change that answer, or Enter when done").strip()
        if not raw:
            break
        if not (raw.isdigit() and 1 <= int(raw) <= 12):
            prompter.say("  Please give a number from 1 to 12, or press Enter.")
            continue
        number = int(raw)
        if number in FIXED_IN_BRIEF:
            prompter.say(f"  Changing {FIXED_IN_BRIEF[number]} changes which rules apply; "
                         f"it is not an answer edit, so the brief leaves it as it is.")
            continue
        question = onboarding.QUESTIONS[number - 1]
        answers[question.key] = onboarding.ask_one(prompter, question, answers,
                                                   current=answers.get(question.key))

    changed = [q for q in onboarding.QUESTIONS if answers.get(q.key) != original.get(q.key)]
    if not changed:
        prompter.say("Nothing changed.")
        return 0
    marks = " ".join(q.number for q in changed)
    if not ask(prompter, Question("brief.approve", "approve", 0,
                                  f"Record the changes to {marks} as one amendment?",
                                  "yes_no", default=True)):
        prompter.say("Nothing was written.")
        return 1

    clean = scaffold.validate_answers(answers)
    files = {
        scaffold.PRODUCT_MD: scaffold.product_md(name, clean),
        scaffold.NEVER_MD: scaffold.never_md(clean),
        scaffold.BRIEF_YML: scaffold.brief_yml(clean, profile=answers["profile"],
                                               brand=answers.get("brand")),
    }
    if any(q.key == "first_version" for q in changed):
        files[scaffold.QUEUE_YML] = scaffold.queue_yml(clean)
    for relative, data in files.items():
        (project / relative).write_bytes(data)
    gitio.git(project, "add", "--", *files)
    gitio.git(project, "commit", "--quiet", "-m", f"amend: brief ({marks})")
    sync = generated.refresh(project)
    prompter.say(f"Amended {name} ({marks}); the constitution is current (sync: {sync}).")
    return 0


# --- taller project show ------------------------------------------------------

def show(args: Any, prompter: Prompter) -> int:
    project = common.project_path(args.path)
    entry = registry.get_project(project)
    brand = entry.get("brand") or "none"
    state = "adopted" if registry.is_adopted(entry) else "discovered, not adopted yet"
    lines = [f"{entry['name']}  ({state})", f"  {entry['path']}",
             f"  Profile {entry['profile']} · brand {brand}"]
    if registry.is_adopted(entry) and (project / scaffold.BRIEF_YML).is_file():
        lines += ["", onboarding.brief_text(entry["name"], scaffold.load_brief(project))]
    queue_path = project / scaffold.QUEUE_YML
    if queue_path.is_file():
        queue = yaml.safe_load(queue_path.read_text(encoding="utf-8")) or {}
        proposed = [item.get("title", "") for item in queue.get("proposed") or []]
        lines += ["", f"Queue: {len(proposed)} proposed"] + [f"  - {t}" for t in proposed]
    prompter.say("\n".join(lines))
    return 0


# --- taller project discover (spec 4.7) ---------------------------------------

def discover(args: Any, prompter: Prompter) -> int:
    """Rounds 3 and 4 again: what is new, moved or gone. Writes nothing."""
    folders = [Path(p) for p in args.roots] or [common.project_path(None).resolve().parent]
    registered = registry.list_projects()
    known = {entry["path"] for entry in registered}
    found = discovery.scan_roots(folders)
    new = [repo for repo in found if repo["path"] not in known]
    gone = set(registry.missing_paths())
    # A registered path that vanished, and an unknown repository of the same name
    # that appeared: most likely the same project, moved.
    moved = [(entry["name"], entry["path"], repo["path"]) for entry in registered
             if entry["path"] in gone for repo in new if repo["name"] == entry["name"]]
    new = [repo for repo in new if repo["path"] not in {to for _, _, to in moved}]
    gone -= {old for _, old, _ in moved}
    listing, note = discovery.list_remote()
    buckets = discovery.reconcile(new, listing)
    clusters = [c for c in discovery.cluster_palettes(
        {repo["name"]: discovery.palette(repo["path"]) for repo in new}) if c["tokens"]]

    lines = [f"Looked in {', '.join(str(f) for f in folders)}"]
    lines += [f"  New: {repo['name']} ({repo['path']})" for repo in new]
    lines += [f"  Moved: {name} is now at {to}" for name, _, to in moved]
    lines += [f"  Gone: {path}" for path in sorted(gone)]
    lines += [f"  Remote does not resolve: {repo['name']} → {repo['origin']}"
              for repo in buckets["stale"]]
    lines += [f"  On GitHub, not cloned here: {repo['name']}" for repo in buckets["remote_only"]
              if repo["key"] not in {discovery.remote_key(_origin_of(e)) for e in registered}]
    lines += [f"  Shared palette: {', '.join(c['repos'])}" for c in clusters
              if len(c["repos"]) > 1]
    if note:
        lines.append(f"  {note}")
    if len(lines) == 1:
        lines.append("  Nothing new.")
    elif new or moved:
        lines.append("`taller setup` registers what is new.")
    prompter.say("\n".join(lines))
    return 0


def _origin_of(entry: dict) -> str | None:
    if not Path(entry["path"]).is_dir():
        return None
    completed = gitio.git(entry["path"], "config", "--get", "remote.origin.url", check=False)
    return completed.stdout.strip() or None


# --- taller project adopt (spec 11.2, 11.3) -----------------------------------

def adopt(args: Any, prompter: Prompter) -> int:
    project = common.project_path(args.path).resolve()
    gitio.require_clean_main(project, "`taller project adopt`")
    try:
        entry = registry.get_project(project)
    except ConfigError:
        entry = None
    if entry and registry.is_adopted(entry):
        raise ConfigError(f"{entry['name']} is already adopted. `taller project brief` "
                          f"changes its answers.")
    if (project / ".taller").exists():
        raise ConfigError(f"{project} already has a .taller directory that Taller did not "
                          f"register. Move it aside first, so nothing of it is lost.")
    name = args.name or (entry["name"] if entry else adopt_lib.slugify(project.name))
    if not brands.SLUG.match(name or ""):
        raise ConfigError(f"{name!r} is not a usable project name; pass --name.")
    open_pages = not args.no_open

    if setup_command.needed():
        setup_command.run_inline(prompter)

    facts = adopt_lib.derive(project)
    prompter.say("\n".join([f"\nAdopting {name} from {project}", "  Found:"] +
                           [f"    - {line}" for line in _found(facts)]))

    presets: dict[str, Any] = {"deploy": facts["deploy"]}
    if facts["profile"]:
        presets["profile"] = facts["profile"]
    if entry:                             # registered by `setup`: its guesses stand
        presets["profile"] = entry["profile"]
    extra: tuple = ()
    if facts["matching_brand"]:
        presets["brand"] = facts["matching_brand"]
    elif facts["tokens"]:
        extra = ((adopt_lib.LIFT, f"a new brand from {facts['stylesheet']} "
                                  f"({len(facts['tokens'])} tokens)"),)
        presets["brand"] = adopt_lib.LIFT
    answers = onboarding.run(name, prompter, presets=presets, extra_brands=extra,
                             new_brand=lambda p: brand_command.create(p, open_page=open_pages))

    new_brand = None
    if answers["brand"] == adopt_lib.LIFT:
        slug = brand_command._slug(prompter, None)
        intent = ask(prompter, Question(
            "adopt.brand.intent", "intent", 0,
            "In one line: what should this brand feel like, and what is each colour for?",
            "text"))
        new_brand = (slug, intent)
        answers["brand"] = slug

    keep_review_dirs = False
    architecture = None
    if facts["claude_md"]:
        prompter.say(f"\nReading the old CLAUDE.md (≈{facts['claude_md_tokens']} tokens) to "
                     f"keep only what is specific to {name}. One dispatch.")
        architecture, error = _distilled(name, facts["claude_md"], answers["profile"])
        if error:
            prompter.say(f"  That did not work ({error}). The old file will be archived "
                         f"instead: kept, never loaded.")

    while True:
        notes = _adoption_notes(facts, answers, new_brand, architecture, keep_review_dirs)
        tokens = facts["tokens"] if new_brand else None
        page = onboarding.write_brief(name, answers, notes, tokens)
        prompter.say("\n" + onboarding.brief_text(name, answers, notes))
        if architecture:
            prompter.say("\n  architecture.md, as proposed:\n"
                         + "\n".join(f"    {line}" for line in architecture.splitlines()))
        prompter.say(f"\nThe brief is at {page}")
        if open_pages:
            brand_command.open_in_browser(page)
        choices = [("approve", "approve and adopt it"), ("edit", "change an answer")]
        if architecture:
            choices.append(("archive", "archive the old CLAUDE.md instead of this summary"))
        if facts["review_dirs"] or facts["review_workflows"]:
            choices.append(("reviews", "remove the old review files after all"
                            if keep_review_dirs else "keep the old review files"))
        choices.append(("cancel", "stop here"))
        decision = ask(prompter, Question("brief", "brief", 0, "Adopt it from this brief?",
                                          "choice", choices=tuple(choices)))
        if decision == "approve":
            break
        if decision == "cancel":
            prompter.say(f"Nothing was changed. Your answers are kept: "
                         f"`taller project adopt` picks up from here.")
            return 1
        if decision == "archive":
            architecture = None
            continue
        if decision == "reviews":
            keep_review_dirs = not keep_review_dirs
            continue
        raw = prompter.ask("brief.edit", "  Which question, 1 to 12?").strip()
        if raw.isdigit() and 1 <= int(raw) <= 12:
            onboarding.edit(name, prompter, answers, int(raw))
        else:
            prompter.say("  Please give a number from 1 to 12.")

    sync = adopt_lib.apply(project, name=name, answers=answers, facts=facts,
                           new_brand=new_brand, architecture=architecture,
                           remove=[] if keep_review_dirs else
                           [*facts["review_dirs"], *facts["review_workflows"]])
    onboarding.discard_progress(name)
    prompter.say("\n".join([
        "",
        f"Adopted {name} (sync: {sync}).",
        f"  Always loaded now: ≈{adopt_lib.preamble_tokens(project)} tokens "
        f"(was ≈{facts['claude_md_tokens']} in CLAUDE.md)",
        f"  Local constitution: {adopt_lib.local_content_chars(project)} characters",
        "  `taller doctor` checks it; `taller project brief` changes an answer.",
    ]))
    return 0


def _distilled(name: str, claude_md: str, profile: str) -> tuple[str | None, str | None]:
    """One distillation per adoption, however many times a chat reruns the command
    (plugin review, I2): the owner approves the text they were shown."""
    import hashlib
    import json

    cache = paths.onboarding(name).with_suffix(".distilled.json")
    stamp = hashlib.sha1(f"{profile}\n{claude_md}".encode("utf-8")).hexdigest()
    try:
        kept = json.loads(cache.read_text(encoding="utf-8"))
        if kept.get("stamp") == stamp and kept.get("architecture"):
            return kept["architecture"], None
    except (OSError, ValueError):
        pass
    architecture, error = adopt_lib.distill(claude_md, profile)
    if architecture:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"stamp": stamp, "architecture": architecture}),
                         encoding="utf-8")
    return architecture, error


def _found(facts: dict) -> list[str]:
    lines = [f"looks like {facts['profile'] or 'no catalogue profile'}"]
    if facts["tokens"]:
        lines.append(f"{len(facts['tokens'])} design tokens in {facts['stylesheet']}"
                     + (f", identical to the brand {facts['matching_brand']}"
                        if facts["matching_brand"] else ""))
    if facts["claude_md"]:
        lines.append(f"a CLAUDE.md of ≈{facts['claude_md_tokens']} tokens")
    if facts["smoke_boot"]:
        lines.append(f"started with `{facts['smoke_boot']}`")
    lines.append(f"{facts['commits']} commits; "
                 + ("tests in tests/" if facts["tests"] else "no tests/ directory"))
    if facts["review_dirs"]:
        lines.append("review directories Taller's gates replace: "
                     + ", ".join(f"{name}/" for name in facts["review_dirs"]))
    if facts["review_workflows"]:
        lines.append("review workflows Taller's own check replaces: "
                     + ", ".join(facts["review_workflows"]))
    return lines


def _adoption_notes(facts: dict, answers: dict, new_brand: tuple | None,
                    architecture: str | None, keep_review_dirs: bool = False
                    ) -> tuple[str, ...]:
    notes = []
    brand = answers.get("brand")
    if facts["tokens"] and brand in (facts["matching_brand"], new_brand and new_brand[0]):
        where = "a new hub brand" if new_brand else f"the hub brand {brand}"
        notes.append(f"The {len(facts['tokens'])} tokens in {facts['stylesheet']} move to "
                     f"{where}; its :root block is replaced by an import of the "
                     f"generated file.")
    elif facts["tokens"]:
        notes.append(f"The tokens in {facts['stylesheet']} stay where they are: the chosen "
                     f"brand is not theirs, so the gates will report them as hardcoded.")
    if facts["claude_md"]:
        notes.append("CLAUDE.md becomes a short pointer to the index; "
                     + (f"what is specific to this project goes to architecture.md "
                        f"({len(architecture)} characters)" if architecture else
                        "the old text is archived in .taller/archive/, never loaded")
                     + ". The original stays in git history.")
    for name in facts["review_dirs"]:
        notes.append(f"{name}/ stays: you chose to keep it." if keep_review_dirs else
                     f"{name}/ is replaced by Taller's gates - removed in the adoption "
                     f"commit (still in git history).")
    for path in facts["review_workflows"]:
        notes.append(f"{path} stays: you chose to keep it." if keep_review_dirs else
                     f"{path} is replaced by Taller's own check - removed in the adoption "
                     f"commit (still in git history).")
    notes.append(f"{scaffold.CI_WORKFLOW} is written: your rules, sizes and tests run on "
                 f"every push.")
    notes.append("One commit on main, then the generated files are written.")
    return tuple(notes)
