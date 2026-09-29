"""Adoption: bring an existing repository under Taller (spec 11.2, 11.3, 4.2.1).

Derive facts, interview intent. `derive` reads what the repository can answer —
stack, tokens and where they live, deploy shape, the old `CLAUDE.md` — and
writes nothing. The interview then asks only what no scan can answer, with the
inferences shown for correction.

Two things move at adoption rather than being flagged:

* **The tokens** (4.2.1). A project that defines its palette in its own
  stylesheet would otherwise report every definition as a hardcoded value. They
  are lifted into the hub brand, the `:root` block leaves the stylesheet, and an
  `@import` of the generated file takes its place.
* **The old `CLAUDE.md`** (decision A1). One read-only dispatch keeps only what
  is specific to this project, as `architecture.md`, reviewed in the brief. What
  the hub already says is not repeated, so adoption reduces text (11.3). The
  original stays in git history. If the dispatch fails, the file is archived
  instead - kept, never loaded.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from typing import Any, Mapping

from . import (brands, catalogue, config, constitution, discovery, generated, gitio, hub,
               inference, paths, registry, scaffold)
from .errors import ConfigError

Facts = dict[str, Any]

REVIEW_DIRS = ("code-review", "security-review", "design-review")
# The workflows Taller's own check replaces (spec 9.4, 13).
REVIEW_WORKFLOWS = (".github/workflows/code-review.yml",
                    ".github/workflows/security.yml",
                    ".github/workflows/design-review.yml")
SMOKE_CANDIDATES = (
    ("run_local.py", "python run_local.py"),
    ("wsgi.py", "gunicorn wsgi:app"),
    ("docker-compose.yml", "docker compose up"),
)
ARCHIVE_CLAUDE_MD = ".taller/archive/CLAUDE.md"
LIFT = "__lift__"

# Criterion 7 caps authored local content at 2,000 characters, and the product,
# never and overrides slices take roughly 1,100 of it.
ARCHITECTURE_MAX = 800
_ROUTE = re.compile(r"@\w+\.(?:route|get|post|put|patch|delete)\(")


# --- derive ------------------------------------------------------------------

def derive(path: Path | str) -> Facts:
    """What the repository can answer for itself. Writes nothing."""
    repo = Path(path)
    stylesheet, tokens = token_source(repo)
    claude = repo / "CLAUDE.md"
    claude_text = claude.read_text(encoding="utf-8", errors="replace") if claude.is_file() else None
    count = gitio.git(repo, "rev-list", "--count", "HEAD", check=False)
    return {
        "profile": discovery.guess_profile(repo),
        "stylesheet": stylesheet,
        "tokens": tokens,
        "matching_brand": matching_brand(tokens),
        "deploy": "docker" if any((repo / name).is_file() for name in
                                  ("docker-compose.yml", "compose.yml", "Dockerfile"))
                  else "local",
        "smoke_boot": next((command for name, command in SMOKE_CANDIDATES
                            if (repo / name).is_file()), None),
        "tests": (repo / "tests").is_dir(),
        "route_files": _route_files(repo),
        "commits": int(count.stdout.strip()) if count.returncode == 0 else 0,
        "claude_md": claude_text,
        "claude_md_tokens": constitution.estimate_tokens(claude_text) if claude_text else 0,
        # Only what git tracks: `git rm` of an ignored folder fails half-way through
        # the adoption commit, and there is nothing of the owner's history to retire.
        "review_dirs": [name for name in REVIEW_DIRS if (repo / name).is_dir() and gitio.git(
            repo, "ls-files", "--", name, check=False).stdout.strip()],
        "review_workflows": [path for path in REVIEW_WORKFLOWS if (repo / path).is_file()
                             and gitio.git(repo, "ls-files", "--", path,
                                           check=False).stdout.strip()],
    }


def token_source(repo: Path) -> tuple[str | None, dict[str, str]]:
    """The stylesheet that defines the palette, and its tokens.

    The one with the most `:root` tokens wins; vendored and minified files are
    never candidates, or Bootstrap would be adopted as the brand.
    """
    best: tuple[str | None, dict[str, str]] = (None, {})
    for css in discovery._files(repo, lambda p: p.suffix.lower() == ".css"
                                and not p.name.lower().endswith(".min.css")):
        tokens = brands.tokens_in(css.read_text(encoding="utf-8", errors="replace"))
        if len(tokens) > len(best[1]):
            best = (css.relative_to(repo).as_posix(), tokens)
    return best


def matching_brand(tokens: Mapping[str, str]) -> str | None:
    """A hub brand with exactly this palette, so adoption never duplicates one."""
    if not tokens:
        return None
    wanted = {name: discovery._normalise_value(value) for name, value in tokens.items()}
    for slug in brands.list_brands():
        text = (paths.brands() / slug / "tokens.css").read_text(encoding="utf-8")
        have = {name: discovery._normalise_value(value)
                for name, value in brands.tokens_in(text).items()}
        if have == wanted:
            return slug
    return None


def _route_files(repo: Path) -> list[str]:
    found = []
    for file in discovery._files(repo, lambda p: p.suffix == ".py"):
        relative = file.relative_to(repo).as_posix()
        if relative.startswith("tests/"):
            continue
        if _ROUTE.search(file.read_text(encoding="utf-8", errors="replace")):
            found.append(relative)
    return found


# --- the token lift (spec 4.2.1) ---------------------------------------------

def import_href(stylesheet: str, tokens_path: str) -> str:
    """The generated file as the stylesheet must name it: relative, POSIX."""
    return posixpath.relpath(tokens_path, posixpath.dirname(stylesheet) or ".")


def lift_stylesheet(css: str, href: str) -> str:
    """The stylesheet without its `:root` blocks, importing the generated tokens.

    `@import` must precede every rule, so it goes first - after `@charset`, which
    must be first of all.
    """
    statement = f'@import url("{href}");'
    body = re.sub(r":root\s*\{[^}]*\}\s*\n?", "", css)
    body = re.sub(r"\n{3,}", "\n\n", body).lstrip("\n")
    if statement in body:
        return body
    charset = re.match(r'@charset\s+"[^"]*";\s*\n?', body)
    if charset:
        return body[: charset.end()] + statement + "\n" + body[charset.end():]
    return statement + "\n" + body


def merge_gitattributes(existing: str | None, brand_tokens: str | None) -> bytes:
    """An adopted project keeps its own attributes; Taller adds its lines.

    Only the generated files' lines are added. `* text=auto eol=lf` for the
    whole repository would renormalise every file the owner has, in a commit
    that was meant to be about Taller.
    """
    if existing is None:
        return scaffold.render_gitattributes(brand_tokens)
    wanted = [line for line in scaffold.render_gitattributes(brand_tokens)
              .decode("utf-8").splitlines() if "merge=ours" in line]
    missing = [line for line in wanted if line not in existing.splitlines()]
    if not missing:
        return existing.encode("utf-8")
    text = existing.rstrip("\n") + "\n\n# Taller: generated files, regenerated and never merged.\n"
    return (text + "\n".join(missing) + "\n").encode("utf-8")


# --- the old CLAUDE.md (decision A1) -----------------------------------------

DISTILL_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "architecture_md": {"type": "string"},
    },
    "required": ["summary", "architecture_md"],
}


def distill_prompt(claude_md: str, hub_rules: str) -> str:
    return "\n".join([
        "A project is moving its instructions out of its old CLAUDE.md. From now on",
        "it inherits the SHARED RULES below, so anything they already say must not",
        "be repeated.",
        "",
        "Write the project's architecture.md: only what is specific to this project",
        "- its layers and key modules, how data flows, decisions that are not",
        "obvious from the code, and traps a newcomer would fall into. Leave out",
        "anything the shared rules cover, generic advice, setup or run instructions,",
        "and anything about how to talk to an assistant.",
        f"At most {ARCHITECTURE_MAX} characters of Markdown, no top-level heading.",
        "Also give a one-line summary of it, under 100 characters.",
        "",
        "=== SHARED RULES ===",
        hub_rules,
        "=== OLD CLAUDE.md ===",
        claude_md,
    ])


def hub_rules(profile: str) -> str:
    """The module text a project on this profile inherits, from hub or catalogue."""
    try:
        data = catalogue.read_hub_profile(profile)
        root = paths.modules()
    except ConfigError:
        data = catalogue.read_profile(profile)
        root = paths.catalogue() / "modules"
    chunks = []
    for module in data.get("modules", []):
        path = root / f"{module}.md"
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n\n".join(chunks)


def distill(claude_md: str, profile: str) -> tuple[str | None, str | None]:
    """`(architecture.md text, None)`, or `(None, reason)` when it could not be done."""
    result = inference.infer(inference.Dispatch(
        role="architect", prompt=distill_prompt(claude_md, hub_rules(profile)),
        config=config.load_hub_config(), schema=DISTILL_SCHEMA,
    ))
    if not result.ok or not isinstance(result.value, dict):
        return None, result.error or "the answer was not in the expected shape"
    summary = scaffold.flatten(result.value.get("summary", ""))
    body = str(result.value.get("architecture_md", "")).strip()
    if not summary or not body:
        return None, "the answer was empty"
    # The index collects every `> ` line (3.1): only the summary may be one.
    body = "\n".join(f"\\{line}" if line.startswith("> ") else line
                     for line in body.splitlines())
    return f"> {summary[:100]}\n\n{body}\n", None


# --- apply -------------------------------------------------------------------

def apply(project: Path | str, *, name: str, answers: Mapping[str, Any], facts: Facts,
          new_brand: tuple[str, str] | None, architecture: str | None,
          remove: list[str] | None = None) -> str:
    """Write the adoption as one commit on `main`, register, resolve. Returns sync.

    `new_brand` is `(slug, intent)` when the lifted tokens become a new hub brand.
    `remove`: superseded review directories (REVIEW_DIRS) the owner let go of,
    removed in the same commit. Called only after the brief is approved.
    """
    project = Path(project)
    gitio.require_clean_main(project, "`taller project adopt`")
    clean = scaffold.validate_answers(answers)
    profile = answers["profile"]
    brand = None if answers["brand"] in (None, "none") else answers["brand"]

    # The hub first: the snapshot records its HEAD (4.6).
    if new_brand:
        brands.write(new_brand[0], facts["tokens"], new_brand[1])
        hub.commit(f"brand: add {new_brand[0]} (lifted from {name})")
    if profile not in catalogue.installed_profiles():
        catalogue.install_profile(profile)
        hub.commit(f"profile: add {profile}")
    tokens_path = (catalogue.read_hub_profile(profile).get("paths") or {}).get("brand_tokens")

    files = scaffold.taller_files(name, clean, profile=profile, brand=brand)
    if architecture:
        files[scaffold.ARCHITECTURE_MD] = architecture.encode("utf-8")
    elif facts.get("claude_md"):
        files[ARCHIVE_CLAUDE_MD] = facts["claude_md"].encode("utf-8")

    lifting = bool(facts.get("tokens") and brand and tokens_path
                   and brand in (facts.get("matching_brand"), new_brand and new_brand[0]))
    if lifting and facts["stylesheet"] != tokens_path:
        sheet = project / facts["stylesheet"]
        lifted = lift_stylesheet(sheet.read_text(encoding="utf-8"),
                                 import_href(facts["stylesheet"], tokens_path))
        files[facts["stylesheet"]] = lifted.encode("utf-8")

    # Every adopted project gets the same check the scaffolds ship (spec 9.4).
    files[scaffold.CI_WORKFLOW] = scaffold.ci_workflow(scaffold.configured_taller_source())

    existing = project / ".gitattributes"
    files[".gitattributes"] = merge_gitattributes(
        existing.read_text(encoding="utf-8") if existing.is_file() else None,
        tokens_path if brand else None)

    for relative, data in files.items():
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    gitio.git(project, "config", "merge.ours.driver", "true")
    gitio.git(project, "add", "--", *files)
    for path in remove or []:
        if path in REVIEW_DIRS and (project / path).is_dir():
            gitio.git(project, "rm", "-r", "--quiet", "--ignore-unmatch", "--", path)
        elif path in REVIEW_WORKFLOWS and (project / path).is_file():
            gitio.git(project, "rm", "--quiet", "--ignore-unmatch", "--", path)
    gitio.git(project, "commit", "--quiet", "-m", f"Adopt {name} into Taller")

    registry.add_project(path=project, name=name, profile=profile, brand=brand, adopted=True)
    gitio.ensure_main_worktree(project)
    return generated.refresh(project)


def local_content_chars(project: Path | str) -> int:
    """Criterion 7: the authored slices, generated files excluded."""
    root = paths.project_constitution(Path(project))
    return sum(len((root / f"{name}.md").read_text(encoding="utf-8"))
               for name in ("product", "architecture", "never", "overrides")
               if (root / f"{name}.md").is_file())


def preamble_tokens(project: Path | str) -> int:
    """Criterion 6: what a session loads before it asks for anything."""
    project = Path(project)
    text = (project / "CLAUDE.md").read_text(encoding="utf-8")
    text += paths.project_index(project).read_text(encoding="utf-8")
    return constitution.estimate_tokens(text)


def slugify(text: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")[:63]
