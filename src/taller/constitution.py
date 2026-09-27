"""Resolution: two chains into one `RuleSet`, and the generated artefacts.

Spec 4.4. Chain 1 is configuration — hub `taller.yml`, then the profile, then the
project's `taller.yml`, by deep merge. Chain 2 is slice text — hub modules in
profile order, then the project's `constitution/`, with its `never.md` appended.
They are separate on purpose: **nothing in `constitution/` sets configuration**,
and prose is **only ever appended**, so a project cannot delete a hub prohibition.
The only way a rule stops applying is an override with a reason (spec 4.5).

`resolve()` writes nothing and calls nothing over the network. That purity is
what makes spec 4.6's byte-for-byte tamper check possible: a `resolve()` that
wrote the snapshot would rewrite the very file the check compares, so the check
could never fail. The renderers serialise; only `gitio.commit_to_main()` writes.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import catalogue, config, overrides, paths, registry
from .errors import ConfigError

RuleSet = dict[str, Any]
ResolvedSlice = dict[str, Any]

# Spec 4.3. Exactly nine, in reading order; the list is closed.
SLICE_NAMES: tuple[str, ...] = (
    "product", "architecture", "stack", "conventions", "security", "ux",
    "brand", "never", "overrides",
)

# Spec 4.3: what makes a project itself. A hub module of one of these names is
# ignored - not merged, not preferred.
PROJECT_ONLY_SLICES = frozenset({"product", "architecture", "overrides"})

# Profile keys that are not configuration and must not reach chain 1. `brand` is
# a slug the registry records per project, not a config value (spec 4.1).
PROFILE_NON_CONFIG_KEYS = frozenset({"name", "description", "modules", "brand"})

_TOKEN = re.compile(r"^\s*(--[A-Za-z0-9_-]+)\s*:\s*([^;]+);", re.MULTILINE)


# --- chain 1 + chain 2 -------------------------------------------------------

def resolve(project_path: Path | str) -> RuleSet:
    """The complete `RuleSet` for a registered project. Pure; writes nothing."""
    project = Path(project_path)
    entry = registry.get_project(project)          # raises ConfigError if unknown
    profile_name = entry["profile"]
    profile = catalogue.read_hub_profile(profile_name)

    missing = catalogue.missing_modules(profile_name)
    if missing:
        raise ConfigError(
            f"Profile {profile_name!r} names modules this hub does not have: "
            f"{', '.join(missing)}. Chain 2 would resolve them into silence, so "
            f"nobody would learn a rule stopped applying. Run `taller setup` or "
            f"restore the module file."
        )

    ruleset: RuleSet = _merge_config(profile, project)
    ruleset["project"] = {
        "path": str(project.resolve()),
        "profile": profile_name,
        "name": entry["name"],
    }
    ruleset["brand"] = _resolve_brand(entry.get("brand"))
    ruleset["slices"] = _resolve_slices(profile, project, ruleset["brand"])
    ruleset["overrides"] = _resolve_overrides(project)
    ruleset["mode"] = "local"
    return ruleset


def _merge_config(profile: dict[str, Any], project: Path) -> RuleSet:
    """Chain 1: hub -> profile -> project, deep merge, later wins (spec 4.4).

    `paths.security_sensitive` and `non_suppressible` append at every level, which
    `config.deep_merge` enforces: a project able to narrow its own security
    surface would make spec 8.2's mandatory gate optional.
    """
    merged = config.load_hub_config()
    profile_config = {
        key: value for key, value in profile.items()
        if key not in PROFILE_NON_CONFIG_KEYS
    }
    merged = config.deep_merge(merged, profile_config)
    merged = config.deep_merge(merged, config.read_project_config(project))

    # A YAML date here would not survive json.dumps in render_snapshot, and the
    # value is informational (spec 5.1: `doctor` warns when it is stale).
    pricing = merged.get("pricing")
    if isinstance(pricing, dict) and isinstance(pricing.get("as_of"), (date, datetime)):
        pricing["as_of"] = pricing["as_of"].isoformat()
    return merged


def _resolve_slices(profile: dict[str, Any], project: Path,
                    brand: dict[str, Any] | None) -> dict[str, ResolvedSlice]:
    """Chain 2: hub modules in profile order, then the project's own file.

    A slice with no sources is **absent** from the result rather than present and
    empty: an absent key says "this project has no product slice", which a caller
    can act on.
    """
    sources: dict[str, list[Path]] = {name: [] for name in SLICE_NAMES}

    for module_id in profile.get("modules", []):
        slice_name = slice_of(module_id)
        if slice_name in PROJECT_ONLY_SLICES:
            continue              # spec 4.3 - ignored, not merged, not preferred
        if slice_name not in sources:
            raise ConfigError(
                f"Module {module_id!r} declares slice {slice_name!r}, which is not "
                f"one of the nine of spec 4.3."
            )
        sources[slice_name].append(paths.modules() / f"{module_id}.md")

    if brand:
        brand_prose = paths.brands() / brand["slug"] / "brand.md"
        if brand_prose.is_file():
            sources["brand"].append(brand_prose)

    for name in SLICE_NAMES:
        project_file = paths.project_constitution(project) / f"{name}.md"
        if project_file.is_file():
            sources[name].append(project_file)

    resolved: dict[str, ResolvedSlice] = {}
    for name in SLICE_NAMES:
        files = [path for path in sources[name] if path.is_file()]
        if not files:
            continue
        resolved[name] = {
            "name": name,
            "sources": [str(path) for path in files],
            "text": _concatenate(files),
        }
    return resolved


def slice_of(module_id: str) -> str:
    """The slice a module provides: its directory, or its own name at the root.

    `never.md` sits at the root of `modules/` because it is the one slice with a
    single file (spec 4.0), so the slice name has to come from somewhere.
    """
    return module_id.split("/")[0]


def _concatenate(files: list[Path]) -> str:
    """Slice text, in application order, LF, one blank line between sources.

    `read_text` normalises CRLF, so a module edited on Windows resolves to the
    same bytes as one edited anywhere else - which spec 4.6 compares.
    """
    chunks = [path.read_text(encoding="utf-8").strip("\n") for path in files]
    return "\n\n".join(chunk for chunk in chunks if chunk) + "\n"


def _resolve_brand(slug: str | None) -> dict[str, Any] | None:
    """`None` when the project's brand is `none` (spec 4.4).

    Values exist only in `brands/<slug>/tokens.css` (spec 4.2), so this is the one
    place they enter the RuleSet. The `--` prefix is kept: it is what the
    constitution gate looks for when it flags the same value used literally.
    """
    if not slug or slug == "none":
        return None
    tokens_path = paths.brands() / slug / "tokens.css"
    if not tokens_path.is_file():
        raise ConfigError(
            f"Brand {slug!r} has no tokens.css at {tokens_path}. Run "
            f"`taller brand new {slug}`, or set the project's brand to none."
        )
    text = tokens_path.read_text(encoding="utf-8")
    return {
        "slug": slug,
        "tokens_path": str(tokens_path),
        "tokens": {name: value.strip() for name, value in _TOKEN.findall(text)},
    }


def _resolve_overrides(project: Path) -> list[dict[str, Any]]:
    """Every override the project records, in file order (spec 4.5).

    The source is repo-relative because it is shown to the owner on a Finding
    (spec 7.4), and because an absolute path would differ per machine.
    """
    path = paths.project_constitution(project) / "overrides.md"
    if not path.is_file():
        return []
    relative = path.relative_to(Path(project)).as_posix()
    return overrides.parse(path.read_text(encoding="utf-8"), source=relative)
