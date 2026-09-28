"""`taller profiles list|update`: the hub's profiles, and bringing one up to date.

An installed profile is the owner's: Taller never overwrites it, because she may
have edited it (`catalogue.install_profile`). The cost is that a Taller which
gains a setting leaves every existing hub without it - once found the hard way,
as a ticket blocked at a smoke check whose configuration predated the release.

`update` adds only what her copy lacks, keeps every value she has, and records
the change as an amendment so every project using the profile is refreshed
(spec 4.6).
"""

from __future__ import annotations

from typing import Any

from .. import catalogue, generated, hub
from ..onboarding import Question, ask
from ..prompter import Prompter


def list_(args: Any, prompter: Prompter) -> int:
    installed = catalogue.installed_profiles()
    if not installed:
        prompter.say("No profiles in this hub yet. `taller setup` installs them.")
        return 0
    lines = []
    for name in installed:
        gaps = catalogue.profile_gaps(name)
        lines.append(f"  {name:<16} " + (f"out of date: no {', '.join(gaps)}" if gaps
                                         else "current"))
    stale = [n for n in installed if catalogue.profile_gaps(n)]
    prompter.say("\n".join(["This hub's profiles:", *lines]
                           + ([f"`taller profiles update {stale[0]}` brings one up to date."]
                              if stale else [])))
    return 0


def update(args: Any, prompter: Prompter) -> int:
    name = args.name
    catalogue.read_hub_profile(name)                   # a clear error if not installed
    gaps = catalogue.profile_gaps(name)
    if not gaps:
        prompter.say(f"{name} is already current with this version of Taller.")
        return 0

    prompter.say("\n".join([
        f"This version of Taller has settings your {name} profile does not:", "",
        *(f"  {gap}" for gap in gaps), "",
        "Adding them keeps every value you have changed; only these are written.",
    ]))
    if not ask(prompter, Question("profiles.update", "update", 0,
                                  f"Add them to {name}?", "yes_no", default=True)):
        prompter.say("Nothing was changed.")
        return 1

    added = catalogue.merge_into_hub_profile(name)
    hub.commit(f"amend: {name} profile brought up to date ({', '.join(added)})")
    touched = generated.refresh_affected(everything=True,
                                         message="taller: resolve after an amendment")
    lines = [f"Added to {name}: {', '.join(added)}."]
    lines += [f"  refreshed {project} (sync: {sync})" for project, sync in touched]
    if not touched:
        lines.append("  No adopted project uses it yet.")
    prompter.say("\n".join(lines))
    return 0
