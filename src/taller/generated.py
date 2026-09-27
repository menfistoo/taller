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
