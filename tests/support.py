"""Building a hub and a project on disk, for the resolution tests.

Both `test_constitution.py` and `test_renderers.py` need the same fixture: a hub
with a profile installed, a project registered against that profile, and whatever
slice files the case is actually about. It lives here so the two files cannot
drift apart (plan, task 14).

Everything is written UTF-8 with LF, because spec 4.6 compares generated files
byte for byte and a CRLF fixture would make the comparison platform dependent.
"""

from __future__ import annotations

import subprocess
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


REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED_VOCABULARY = REPO_ROOT / "tests" / "domain_vocabulary.txt"
# Files allowed to contain the words: the example list itself, the fixtures, and
# the catalogue test that keeps its own list of generic lines of business. `docs/`
# is NOT exempt: the design documents are published with the repository.
VOCABULARY_EXEMPT = ("tests/fixtures/", "tests/domain_vocabulary.txt",
                     "tests/unit/test_catalogue_content.py")


def words_in(path: Path) -> list[str]:
    """A word list file: one word a line, `#` comments and blanks ignored."""
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]


def vocabulary_words() -> list[str]:
    """The example list Taller ships, plus the owner's own from her hub if she has one."""
    from taller import paths

    return list(dict.fromkeys(words_in(SHIPPED_VOCABULARY)
                              + words_in(paths.domain_vocabulary())))


def scan_tracked_files(words: list[str]) -> list[str]:
    """Every tracked file holding one of `words` as a whole word, as "path: word"."""
    import re
    import subprocess

    listed = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files"], capture_output=True,
                            text=True, encoding="utf-8")
    if listed.returncode != 0:
        import pytest

        pytest.skip("not a git checkout; this scan covers tracked files")
    if not words:
        return []
    pattern = re.compile(r"(?<!\w)(" + "|".join(re.escape(w) for w in words) + r")(?!\w)",
                         re.IGNORECASE)
    found: list[str] = []
    for relative in listed.stdout.splitlines():
        if relative.startswith(VOCABULARY_EXEMPT):
            continue
        try:
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue                    # binary: nothing to read
        found += [f"{relative}: {m.group(0)}" for m in pattern.finditer(text)]
    return found


def git(repo: Path, *args: str) -> str:
    """`git` in a repository, as text. Raises on failure."""
    import subprocess

    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


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


def make_pdf(path: Path, lines: list[str], *, fonts: tuple[str, ...] = ("Helvetica",)) -> Path:
    """A minimal, valid PDF: one page, one text line per entry, `fonts` embedded.

    Hand-assembled because no PDF-writing library is a dependency. The first font
    sets the text; every font is listed in the page's resources, which is where a
    real brand guide's typefaces show up. `lines=[]` gives a page with no content
    stream at all - the shape of a scanned PDF with no text layer.
    """
    def escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\(").replace(")", "\)")

    font_refs = " ".join(f"/F{i} {5 + i} 0 R" for i in range(len(fonts)))
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        f"/Resources << /Font << {font_refs} >> >>"
        + (" /Contents 4 0 R" if lines else "") + " >>",
    ]
    body = "".join(
        f"BT /F0 11 Tf 72 {740 - 16 * n} Td ({escape(line)}) Tj ET\n"
        for n, line in enumerate(lines)
    )
    objects.append(f"<< /Length {len(body.encode('latin-1'))} >>\nstream\n{body}endstream")
    objects.extend(
        f"<< /Type /Font /Subtype /Type1 /BaseFont /{name} >>" for name in fonts
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode("latin-1")
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode("latin-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path


def make_repo(path: Path, files: Mapping[str, str], *, origin: str | None = None,
              commit: bool = True, branch: str = "main") -> Path:
    """A real git repository holding `files`, committed on `branch`.

    Identity is passed per command so the fixture does not depend on the
    machine's git configuration.
    """
    import subprocess

    identity = ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "-c", "commit.gpgsign=false"]
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet", "-b", branch, str(path)], check=True)
    for relative, text in files.items():
        write(path / relative, text)
    if origin:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", origin], check=True)
    if commit and files:
        subprocess.run(["git", *identity, "-C", str(path), "add", "--all"], check=True)
        subprocess.run(["git", *identity, "-C", str(path), "commit", "--quiet", "-m",
                        "initial"], check=True)
    return path


ANSWERS = {
    "what_it_does": "Keeps track of which neighbour has borrowed which tool.",
    "what_it_is_not": "A marketplace.", "must_never_break": "Who has which tool.",
    "users": "team", "reach": "a private network", "phone": False,
    "stores": "Tools and loans.", "sensitive_data": False, "deploy": "local",
    "first_version": ["List the tools", "Record a loan", "Show who has what"],
}


def new_project(name: str = "toolshed", *, brand: str | None = None,
                origin: str | None = None) -> Path:
    """A project as `taller project new` leaves it: committed, registered, resolved.

    Needs the `tmp_home` and `identity` fixtures. `origin` adds a remote after
    creation - a path that does not exist makes every push fail, which is how a
    test reaches `sync: pending`.
    """
    import subprocess

    from taller import hub, scaffold

    if not (hub.read_config().get("language") or {}).get("code"):
        hub.update_config({"language": {"code": "en", "ui": "es", "commits": "en"}})
        hub.commit("setup")
    target = paths.home() / "projects" / name
    scaffold.create_project(target, name=name, profile="flask-sqlite", brand=brand,
                            answers=ANSWERS)
    if origin:
        subprocess.run(["git", "-C", str(target), "remote", "add", "origin", origin],
                       check=True)
    return target


def gh_json(payload: Any) -> subprocess.CompletedProcess:
    """What `discovery._run_gh` returns when gh answered with JSON."""
    import json as _json

    return subprocess.CompletedProcess(args=["gh"], returncode=0,
                                       stdout=_json.dumps(payload), stderr="")
