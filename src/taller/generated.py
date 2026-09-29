"""The three generated `main`-side files, rendered and refreshed together.

Spec 4.6: `resolved.json`, `00-index.md` and — when a brand is set —
`paths.brand_tokens` are regenerated together, so none can be stale relative to
another. `render_all` is pure (doctor compares against it in memory); `refresh`
commits them through the only writer.
"""

from __future__ import annotations

from pathlib import Path

from . import constitution, gitio

SNAPSHOT = ".taller/resolved.json"
INDEX = ".taller/constitution/00-index.md"


def render_all(project: Path | str,
               ruleset: constitution.RuleSet | None = None) -> dict[str, bytes]:
    """Repo-relative path -> bytes for every generated file this project has."""
    ruleset = ruleset if ruleset is not None else constitution.resolve(project)
    files = {
        SNAPSHOT: constitution.render_snapshot(ruleset),
        INDEX: constitution.render_index(ruleset),
    }
    tokens = constitution.render_tokens(ruleset)
    tokens_path = gitio.brand_tokens_path(project)
    if tokens is not None and tokens_path:
        files[tokens_path] = tokens
    return files


def refresh(project: Path | str, message: str = "taller: resolve the constitution") -> str:
    """Re-render and commit all three. Returns the sync state (spec 7.3)."""
    return gitio.commit_to_main(project, render_all(project), message)


def refresh_affected(*, module: str | None = None, brand: str | None = None,
                     everything: bool = False,
                     message: str = "taller: resolve after a hub change") -> list[tuple[str, str]]:
    """Refresh every adopted project a hub change reaches (spec 4.6).

    An amend to one shared rule writes to every project using it - one lock, one
    commit and one sync state each - because refreshing only one would leave the
    rest reporting a stale snapshot until someone noticed. Returns
    `(project name, sync)` for each, so the caller can say what it touched.
    """
    from . import catalogue, registry            # registry imports nothing of ours

    touched: list[tuple[str, str]] = []
    for entry in registry.list_projects():
        if not registry.is_adopted(entry) or not Path(entry["path"]).is_dir():
            continue
        reached = everything
        if brand is not None and entry.get("brand") == brand:
            reached = True
        if module is not None:
            try:
                modules = catalogue.read_hub_profile(entry["profile"]).get("modules", [])
            except Exception:                    # a broken profile is doctor's to report
                modules = []
            reached = reached or module in modules
        if reached:
            gitio.ensure_main_worktree(entry["path"])
            touched.append((entry["name"], refresh(entry["path"], message)))
    return touched
