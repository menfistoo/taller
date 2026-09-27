"""`taller setup`: connect, and the three languages (spec 4.7 rounds 1 and 5).

`project new` runs both rounds inline on a hub whose `language` is unset, so a
first-ever user never has to know that `setup` exists (spec 11.1). The full run
adds rounds 2-4 and 6: find the projects, confirm their brands, then one review
screen before anything is written. A discovered project is registered, not
adopted (decision B1): nothing is written into it until `taller project adopt`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import (adopt, brands, catalogue, config, discovery, generated, gitio, hub,
                onboarding, registry)
from ..errors import ConfigError
from ..onboarding import Question, ask
from ..prompter import Prompter
from . import common

LANGUAGE_CODE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})?$")
BILLING_LABELS = {
    "subscription": "your Claude subscription",
    "api": "an Anthropic API key (billed per token)",
    "bedrock": "Amazon Bedrock",
    "vertex": "Google Vertex AI",
}


def needed() -> bool:
    """True when the hub has never been through the language round."""
    language = config.load_hub_config().get("language")
    return not (isinstance(language, dict) and language.get("code"))


# --- round 1: connect --------------------------------------------------------

def connect(prompter: Prompter, *, write: bool = True) -> dict[str, Any]:
    """GitHub, how Claude is reached, and the deployment host.

    Returns the hub changes; writes them only when `write` (the inline rounds).
    """
    prompter.say(discovery.gh_auth_status()["message"])

    detected = config.detect_billing_mode()
    prompter.say(
        f"Claude is reached through the `claude` command, signed in as it already "
        f"is. Detected: {BILLING_LABELS[detected]}. Taller stores no key of its own."
    )
    changes: dict[str, Any] = {}
    right = ask(prompter, Question("setup.billing", "billing", 0, "Is that right?",
                                   "yes_no", default=True))
    if not right:
        mode = ask(prompter, Question(
            "setup.billing.mode", "billing", 0, "How is Claude reached?", "choice",
            choices=tuple(BILLING_LABELS.items())))
        changes["billing"] = {"mode": mode}

    current = (hub.read_config().get("deploy") or {}).get("host") or ""
    host = prompter.ask(
        "setup.host",
        "  The server your projects deploy to, if there is one (Enter for none)"
        + (f"\n     [{current}]" if current else ""),
    ).strip() or current
    if host and host != current:
        changes["deploy"] = {"host": host}
    if write and changes:
        hub.update_config(changes)
    return changes


# --- round 5: languages ------------------------------------------------------

def languages(prompter: Prompter, *, write: bool = True) -> dict[str, str]:
    """Asked, never assumed. No defaults on a hub that has none."""
    current = hub.read_config().get("language") or {}
    chosen = {
        "code": _code(prompter, "setup.language.code",
                      "Language for code, comments and identifiers (for example en)",
                      current.get("code")),
        "ui": _code(prompter, "setup.language.ui",
                    "Language your projects' screens are written in (for example es "
                    "or en), or none for projects without a user interface",
                    current.get("ui"), allow_none=True),
        "commits": _code(prompter, "setup.language.commits",
                         "Language for commit messages (for example en)",
                         current.get("commits")),
    }
    if write:
        hub.update_config({"language": chosen})
    return chosen


def _code(prompter: Prompter, qid: str, text: str, default: Any,
          allow_none: bool = False) -> str:
    prompt = f"  {text}" + (f"\n     [{default}]" if default else "")
    while True:
        raw = prompter.ask(qid, prompt).strip().lower()
        if not raw and default:
            return str(default)
        if LANGUAGE_CODE.match(raw) or (allow_none and raw == "none"):
            return raw
        prompter.say("  Use a language code such as en, es or pt-br"
                     + (", or none." if allow_none else "."))


def run_inline(prompter: Prompter) -> None:
    """What `project new` runs first on an unconfigured hub (spec 11.1)."""
    prompter.say("This is a new hub. Two short questions about how you work come first.")
    connect(prompter)
    languages(prompter)
    hub.commit("setup: connection and languages")


# --- rounds 2-4: locate and discover (spec 4.7) ------------------------------

@dataclass
class Plan:
    """Everything round 6 shows before anything is written."""
    register: list[dict[str, Any]] = field(default_factory=list)   # repo + profile + brand
    brands: list[dict[str, Any]] = field(default_factory=list)     # slug, tokens, repos
    remote_only: list[dict[str, Any]] = field(default_factory=list)
    stale: list[dict[str, Any]] = field(default_factory=list)
    guides: dict[str, list[str]] = field(default_factory=dict)
    listing_note: str = ""


def roots(prompter: Prompter) -> list[Path]:
    """Round 2: where the projects live. Guess: beside the current repository."""
    guess = common.project_path(None).resolve().parent
    while True:
        raw = prompter.ask("setup.roots",
                           "  Folders that hold your projects, separated by ;"
                           f"\n     [{guess}]").strip()
        chosen = [Path(part.strip().strip('"')).expanduser()
                  for part in raw.split(";") if part.strip()] or [guess]
        missing = [str(path) for path in chosen if not path.is_dir()]
        if not missing:
            return chosen
        prompter.say(f"  Not a folder: {', '.join(missing)}")


def discover(prompter: Prompter, folders: list[Path]) -> Plan:
    """Rounds 3 and 4. Asks only what discovery cannot answer; writes nothing."""
    plan = Plan()
    known = {entry["path"] for entry in registry.list_projects()}
    found = [repo for repo in discovery.scan_roots(folders) if repo["path"] not in known]
    listing, plan.listing_note = discovery.list_remote()
    buckets = discovery.reconcile(found, listing)
    plan.remote_only = [repo for repo in buckets["remote_only"]
                        if repo["key"] not in {r.get("key") for r in _registered_keys()}]
    plan.stale = buckets["stale"]
    local = [pair[0] for pair in buckets["linked"]] + buckets["local_only"] + buckets["stale"]
    local.sort(key=lambda repo: repo["path"])
    prompter.say(f"\nFound {len(local)} projects to register"
                 + (f", {len(plan.remote_only)} on GitHub not cloned here"
                    if plan.remote_only else "")
                 + (f". {plan.listing_note}" if plan.listing_note else "."))

    # Round 3's stack guess, asked only where there is none.
    for repo in local:
        profile = discovery.guess_profile(repo["path"])
        if profile is None:
            profile = ask(prompter, Question(
                f"setup.profile.{repo['name']}", "profile", 0,
                f"{repo['name']} ({repo['path']}) matches no profile. Which is it?", "choice",
                choices=tuple(onboarding.profile_choices()) + (("skip", "skip it for now"),)))
        if profile != "skip":
            plan.register.append({**repo, "profile": profile, "brand": None})

    # Round 4: palettes into clusters, clusters into brands to confirm.
    palettes = {repo["path"]: discovery.palette(repo["path"]) for repo in plan.register}
    for repo in plan.register:
        guides = discovery.brand_assets(repo["path"])["guides"]
        if guides:
            plan.guides[repo["name"]] = guides
    names = {repo["path"]: repo["name"] for repo in plan.register}
    for cluster in discovery.cluster_palettes(palettes):
        if not cluster["tokens"]:
            continue
        members = cluster["repos"]
        slug = adopt.matching_brand(cluster["tokens"])
        if slug is None:
            slug = _name_cluster(prompter, cluster, [names[p] for p in members], plan)
            if slug:
                plan.brands.append({"slug": slug, "tokens": cluster["tokens"],
                                    "repos": [names[p] for p in members]})
        for repo in plan.register:
            if repo["path"] in members and slug:
                repo["brand"] = slug
    return plan


def _registered_keys() -> list[dict[str, Any]]:
    return [{"key": discovery.remote_key(_origin(entry["path"]))}
            for entry in registry.list_projects()]


def _origin(path: str) -> str | None:
    completed = gitio.git(path, "config", "--get", "remote.origin.url", check=False)
    return completed.stdout.strip() or None


def _name_cluster(prompter: Prompter, cluster: dict, members: list[str],
                  plan: Plan) -> str | None:
    """Brand confirmation, not brand invention (spec 4.7)."""
    sample = ", ".join(f"{name} {value}" for name, value in list(cluster["tokens"].items())[:4])
    guides = [f"{name}: {', '.join(paths_)}" for name, paths_ in plan.guides.items()
              if name in members]
    taken = set(brands.list_brands()) | {brand["slug"] for brand in plan.brands}
    prompter.say(f"\n  {', '.join(members)} share one palette of {len(cluster['tokens'])} "
                 f"tokens ({sample}…)."
                 + (f"\n  A brand guide was found — {'; '.join(guides)}. `taller brand new` "
                    f"from it is more authoritative than any stylesheet." if guides else ""))
    while True:
        raw = prompter.ask(f"setup.brand.{members[0]}",
                           "  What is this brand called? (Enter to leave it unnamed)").strip()
        if not raw:
            return None
        try:
            brands.validate_slug(raw)
        except ConfigError as exc:
            prompter.say(f"  {exc}")
            continue
        if raw in taken:
            prompter.say(f"  {raw!r} is already taken.")
            continue
        return raw


# --- round 6: review, then write ---------------------------------------------

def review_text(plan: Plan, changes: dict[str, Any]) -> str:
    lines = ["\nAbout to write:"]
    for key, value in changes.items():
        lines.append(f"  hub {key}: {value}")
    if plan.register:
        lines.append(f"  Register {len(plan.register)} projects (nothing is written into them):")
        lines += [f"    {n}) {repo['name']}: {repo['profile']}, brand "
                  f"{repo['brand'] or 'none'}" for n, repo in enumerate(plan.register, 1)]
    for brand in plan.brands:
        lines.append(f"  Create brand {brand['slug']} from {', '.join(brand['repos'])} "
                     f"({len(brand['tokens'])} tokens)")
    profiles = sorted({repo["profile"] for repo in plan.register}
                      - set(catalogue.installed_profiles()))
    if profiles:
        lines.append(f"  Copy from the catalogue: {', '.join(profiles)}")
    if plan.stale:
        lines.append("  Remotes that do not resolve (renamed or deleted?): "
                     + ", ".join(f"{repo['name']} → {repo['origin']}" for repo in plan.stale))
    if plan.remote_only:
        lines.append("  On GitHub, not cloned here (listed only): "
                     + ", ".join(repo["name"] for repo in plan.remote_only))
    return "\n".join(lines)


def apply(plan: Plan, changes: dict[str, Any]) -> list[tuple[str, str]]:
    """Write what round 6 approved. Returns the projects a language change refreshed."""
    if changes:
        hub.update_config(changes)
    for brand in plan.brands:
        brands.write(brand["slug"], brand["tokens"],
                     f"Confirmed from the palette shared by {', '.join(brand['repos'])}.")
    for profile in sorted({repo["profile"] for repo in plan.register}):
        if profile not in catalogue.installed_profiles():
            catalogue.install_profile(profile)
    hub.commit("setup: " + ", ".join(filter(None, [
        "connection and languages" if changes else "",
        f"{len(plan.brands)} brands" if plan.brands else "",
        f"{len(plan.register)} projects" if plan.register else "",
    ])) or "setup")
    for repo in plan.register:
        registry.add_project(path=repo["path"], name=repo["name"], profile=repo["profile"],
                             brand=repo["brand"], adopted=False)
    return generated.refresh_affected(everything=True) if changes else []


def run(args: Any, prompter: Prompter) -> int:
    prompter.say("Connect")
    changes = connect(prompter, write=False)
    prompter.say("\nWhere your projects are")
    plan = discover(prompter, roots(prompter))
    prompter.say("\nLanguages")
    chosen = languages(prompter, write=False)
    if chosen != (hub.read_config().get("language") or {}):
        changes["language"] = chosen

    while True:
        prompter.say(review_text(plan, changes))
        decision = ask(prompter, Question(
            "setup.review", "review", 0, "Write all of this?", "choice",
            choices=(("approve", "approve"), ("edit", "change a project's profile"),
                     ("cancel", "cancel, writing nothing"))))
        if decision == "cancel":
            prompter.say("Nothing was written.")
            return 1
        if decision == "approve":
            break
        _edit_project(prompter, plan)

    touched = apply(plan, changes)
    lines = ["\nDone."]
    if plan.register:
        lines.append(f"  {len(plan.register)} projects registered. Adopt each when you "
                     f"are ready: `taller project adopt <path>`.")
    if touched:
        lines.append(f"  Refreshed for the new languages: {', '.join(n for n, _ in touched)}")
    prompter.say("\n".join(lines))
    return 0


def _edit_project(prompter: Prompter, plan: Plan) -> None:
    raw = prompter.ask("setup.review.project", "  Which project, by number?").strip()
    if not (raw.isdigit() and 1 <= int(raw) <= len(plan.register)):
        prompter.say("  No project has that number.")
        return
    repo = plan.register[int(raw) - 1]
    choice = ask(prompter, Question(
        "setup.review.profile", "profile", 0, f"Profile for {repo['name']}", "choice",
        choices=tuple(onboarding.profile_choices()) + (("skip", "do not register it"),)))
    if choice == "skip":
        plan.register.remove(repo)
    else:
        repo["profile"] = choice


