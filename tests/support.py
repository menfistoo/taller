"""Building a hub and a project on disk, for the resolution tests.

Both `test_constitution.py` and `test_renderers.py` need the same fixture: a hub
with a profile installed, a project registered against that profile, and whatever
slice files the case is actually about. It lives here so the two files cannot
drift apart (plan, task 14).

Everything is written UTF-8 with LF, because spec 4.6 compares generated files
byte for byte and a CRLF fixture would make the comparison platform dependent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from taller import catalogue, paths, registry

# A minimal brand, in the shape spec 4.0 gives: values only in tokens.css,
# names only in brand.md.
BRAND_TOKENS_CSS = """:root {
  --color-primary: #1b365d;
  --color-accent: #c8a45c;
  --font-body: "Inter", sans-serif;
}
"""

BRAND_PROSE = """> Which token applies where, by name and never by value.

Use `--color-primary` for chrome and `--color-accent` for a single call to action.
"""


def write(path: Path, text: str) -> Path:
    """UTF-8, LF, parents created. The only way this module writes a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def make_brand(slug: str, *, tokens_css: str = BRAND_TOKENS_CSS,
               prose: str = BRAND_PROSE) -> Path:
    """A hub brand folder: tokens.css holds the values, brand.md the intent."""
    folder = paths.brands() / slug
    write(folder / "tokens.css", tokens_css)
    write(folder / "brand.md", prose)
    return folder


def make_project(
    *,
    name: str = "demo",
    profile: str = "flask-sqlite",
    brand: str | None = None,
    hub_config: Mapping[str, Any] | None = None,
    project_config: Mapping[str, Any] | None = None,
    slices: Mapping[str, str] | None = None,
    profile_patch: Mapping[str, Any] | None = None,
    hub_modules: Mapping[str, str] | None = None,
    register: bool = True,
) -> Path:
    """A hub with `profile` installed and a registered project resolved against it.

    `slices` are project constitution files, keyed by slice name; `hub_modules`
    are extra hub module files, keyed by module id. `profile_patch` is merged into
    the installed hub profile, which is how a test builds a profile that names a
    module the hub lacks.
    """
    catalogue.install_profile(profile)

    if hub_config is not None:
        write(paths.hub_config(), yaml.safe_dump(dict(hub_config), sort_keys=False))

    for module_id, text in (hub_modules or {}).items():
        write(paths.modules() / f"{module_id}.md", text)

    if profile_patch is not None:
        path = paths.profiles() / f"{profile}.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data.update(profile_patch)
        write(path, yaml.safe_dump(data, sort_keys=False))

    if brand:
        make_brand(brand)

    project = paths.home() / "projects" / name
    paths.project_constitution(project).mkdir(parents=True, exist_ok=True)

    for slice_name, text in (slices or {}).items():
        write(paths.project_constitution(project) / f"{slice_name}.md", text)

    if project_config is not None:
        write(paths.project_config(project),
              yaml.safe_dump(dict(project_config), sort_keys=False))

    if register:
        registry.add_project(path=project, name=name, profile=profile, brand=brand)

    return project


def tree_mtimes(root: Path) -> dict[str, tuple[float, int]]:
    """Every file under `root`, by mtime and size.

    Both, because a write fast enough to reuse the same mtime still changes the
    size, and a same-size rewrite still moves the mtime.
    """
    return {
        str(path): (path.stat().st_mtime_ns, path.stat().st_size)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
