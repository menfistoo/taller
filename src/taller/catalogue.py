"""Reading the shipped catalogue, and copying entries into a hub.

The catalogue is inert (spec 4.0): nothing in it is resolved, loaded or enforced
until it lands in `~/.taller/`. This module is the only way it gets there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import locking, paths
from .errors import ConfigError


@dataclass
class InstallReport:
    """What an install actually changed, so a caller can tell the owner."""
    profile: str
    modules_copied: list[str] = field(default_factory=list)
    modules_kept: list[str] = field(default_factory=list)
    profile_copied: bool = False


def list_profiles() -> list[str]:
    """Every profile the catalogue offers, whatever the hub holds.

    A picker on an empty hub has nothing else to show (spec 4.7), so this reads the
    catalogue rather than the hub.
    """
    return sorted(p.stem for p in paths.catalogue().joinpath("profiles").glob("*.yml"))


def read_profile(name: str) -> dict:
    """A catalogue profile, as data. Raises if it does not exist."""
    path = paths.catalogue() / "profiles" / f"{name}.yml"
    if not path.is_file():
        raise ConfigError(
            f"The catalogue has no profile named {name!r}. It offers: "
            f"{', '.join(list_profiles())}."
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{path} does not contain a mapping.")
    return data


def install_profile(name: str) -> InstallReport:
    """Copy a profile and every module it names into the hub.

    Atomic in the sense that matters: the profile is written only after all of its
    modules are in place, so a hub never holds a profile whose modules are missing
    — which is what chain 2 would resolve as dangling references.

    Never overwrites. A module already in the hub is the owner's, possibly edited.
    """
    data = read_profile(name)
    report = InstallReport(profile=name)

    with locking.hub_lock():
        for module in data.get("modules", []):
            source = paths.catalogue() / "modules" / f"{module}.md"
            if not source.is_file():
                raise ConfigError(
                    f"Profile {name!r} names module {module!r}, which the catalogue "
                    f"does not contain."
                )
            target = paths.modules() / f"{module}.md"
            if target.exists():
                report.modules_kept.append(module)
                continue
            locking.atomic_write_text(target, source.read_text(encoding="utf-8"))
            report.modules_copied.append(module)

        profile_target = paths.profiles() / f"{name}.yml"
        if not profile_target.exists():
            source = paths.catalogue() / "profiles" / f"{name}.yml"
            locking.atomic_write_text(profile_target, source.read_text(encoding="utf-8"))
            report.profile_copied = True

    return report


def installed_profiles() -> list[str]:
    """Profiles already in the hub. Empty on a fresh install."""
    if not paths.profiles().is_dir():
        return []
    return sorted(p.stem for p in paths.profiles().glob("*.yml"))


def hub_profile_path(name: str) -> Path:
    return paths.profiles() / f"{name}.yml"


def read_hub_profile(name: str) -> dict:
    path = hub_profile_path(name)
    if not path.is_file():
        raise ConfigError(
            f"{name!r} is not installed in this hub. Installed: "
            f"{', '.join(installed_profiles()) or 'none'}."
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{path} does not contain a mapping.")
    return data


def missing_modules(name: str) -> list[str]:
    """Modules a hub profile names but the hub lacks. `doctor` fails on these."""
    data = read_hub_profile(name)
    return [
        module for module in data.get("modules", [])
        if not (paths.modules() / f"{module}.md").is_file()
    ]
