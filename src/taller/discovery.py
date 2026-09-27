"""Discovery: projects on disk and on GitHub, and the brands they already share.

Spec 4.7. A hub starts empty, and registering ten projects by hand is something
nobody does twice. Discovery finds what exists; `taller setup` shows it and
writes only after the owner approves. So everything here is a read: no
function in this module writes a file, clones, or creates a remote.

Round 4's point is that brand creation becomes brand *confirmation*: projects
whose stylesheets carry an identical palette are proposed as one brand, and a
PDF that looks like a guide is surfaced as the authoritative source.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from . import brands

LocalRepo = dict[str, Any]
RemoteRepo = dict[str, Any]
Buckets = dict[str, list]

# Never descended into: dependencies, environments, build output, vendored code.
# A root holding one project with a node_modules must not take minutes.
SKIP_DIRS = frozenset({
    "node_modules", "venv", ".venv", "env", "__pycache__", "site-packages",
    "dist", "build", "vendor", "vendors", "bower_components",
})
GUIDE_WORDS = ("brand", "guide", "manual", "identity", "style")
GH_TIMEOUT = 60.0
LS_REMOTE_TIMEOUT = 20.0

_SCP_LIKE = re.compile(r"^(?:[\w.-]+@)?([\w.-]+):(?!//)([^\s]+)$")
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([^/:]+)(?::\d+)?/([^\s]+)$", re.I)


# --- projects on disk --------------------------------------------------------

def scan_roots(roots: Iterable[Path | str], *, max_depth: int = 4) -> list[LocalRepo]:
    """Every repository under the roots, sorted by path. Missing roots skipped."""
    found: dict[str, LocalRepo] = {}
    for root in roots:
        root = Path(root)
        if root.is_dir():
            for repo in _walk_for_repos(root, max_depth):
                found.setdefault(str(repo), _describe(repo))
    return [found[key] for key in sorted(found)]


def _walk_for_repos(root: Path, max_depth: int) -> Iterable[Path]:
    if (root / ".git").exists():
        yield root
        return
    stack = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            children = sorted(p for p in current.iterdir() if p.is_dir())
        except OSError:
            continue                     # unreadable: not ours to report on
        for child in children:
            if child.name.startswith(".") or child.name in SKIP_DIRS:
                continue
            if (child / ".git").exists():
                yield child              # and not into it: nested repos are its own
            elif depth + 1 < max_depth:
                stack.append((child, depth + 1))


def _describe(repo: Path) -> LocalRepo:
    origin = _origin_of(repo)
    return {
        "path": str(repo.resolve()),
        "name": repo.name,
        "origin": strip_credentials(origin) if origin else None,
        "key": remote_key(origin) if origin else None,
    }


def _origin_of(repo: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=LS_REMOTE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    url = completed.stdout.strip()
    return url if completed.returncode == 0 and url else None


def strip_credentials(url: str) -> str:
    """`https://user:token@host/...` -> `https://host/...`.

    A token in a remote URL must never reach a report, the registry or a log.
    """
    return re.sub(r"^([a-z][a-z0-9+.-]*://)[^@/]*@", r"\1", url, flags=re.I)


def remote_key(url: str | None) -> str | None:
    """`host/owner/repo`, lowercased, for any spelling of a hosted remote.

    `None` for a local path or anything else without a host: those cannot be
    matched against a listing.
    """
    if not url:
        return None
    url = url.strip()
    match = _URL.match(url) or _SCP_LIKE.match(url)
    if not match:
        return None
    host, rest = match.group(1), match.group(2)
    rest = rest.strip("/")
    if rest.endswith(".git"):
        rest = rest[:-4]
    parts = [part for part in rest.split("/") if part]
    if len(parts) < 2:
        return None
    return f"{host}/{parts[-2]}/{parts[-1]}".lower()


# --- projects on GitHub ------------------------------------------------------

def list_remote() -> tuple[list[RemoteRepo] | None, str]:
    """The account's repositories, or `(None, reason)` — never an exception.

    Round 1 reports the reason; discovery still works on disk without `gh`.
    """
    completed = _run_gh(["repo", "list", "--limit", "1000",
                         "--json", "nameWithOwner,url,isPrivate"])
    if completed is None:
        return None, "gh is not installed, so repositories on GitHub cannot be listed."
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        return None, detail[0] if detail else f"gh exited {completed.returncode}."
    try:
        rows = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return None, "gh returned something that is not JSON."
    return [
        {"name": row["nameWithOwner"], "key": remote_key(row["url"]),
         "url": row["url"], "private": bool(row.get("isPrivate"))}
        for row in rows
    ], ""


REQUIRED_GH_SCOPES = ("repo", "workflow")


def gh_auth_status() -> dict[str, Any]:
    """Setup round 1 (spec 4.7): who `gh` is signed in as, and what it may do.

    Parsed, never echoed: the raw output carries a (masked) token line, and a
    report is no place for any part of a token.
    """
    completed = _run_gh(["auth", "status"])
    if completed is None:
        return {"ok": False, "account": None, "scopes": [], "missing": [],
                "message": "gh is not installed. GitHub is optional: projects work "
                           "locally, and a remote is only created when you ask."}
    text = f"{completed.stdout}\n{completed.stderr}"
    account = re.search(r"Logged in to \S+ (?:account|as) (\S+)", text)
    if completed.returncode != 0 or not account:
        return {"ok": False, "account": None, "scopes": [], "missing": [],
                "message": "gh is not signed in. Run `gh auth login` when you want "
                           "GitHub; nothing here needs it."}
    scope_line = re.search(r"Token scopes:\s*(.*)", text)
    scopes = re.findall(r"'([^']+)'", scope_line.group(1)) if scope_line else []
    missing = [scope for scope in REQUIRED_GH_SCOPES if scope not in scopes]
    message = f"gh is signed in as {account.group(1)}."
    if missing:
        message += (f" It lacks {', '.join(missing)}; run "
                    f"`gh auth refresh -s {','.join(missing)}` before pushing workflows.")
    return {"ok": True, "account": account.group(1), "scopes": scopes,
            "missing": missing, "message": message}


def _run_gh(args: list[str]) -> subprocess.CompletedProcess | None:
    """`gh`, resolved to an absolute path (Windows skips `.cmd` otherwise)."""
    executable = shutil.which("gh")
    if executable is None:
        return None
    env = dict(os.environ, GH_PROMPT_DISABLED="1", NO_COLOR="1")
    try:
        return subprocess.run([executable, *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=GH_TIMEOUT,
                              env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


# --- the four buckets --------------------------------------------------------

def reconcile(local: list[LocalRepo], remote: list[RemoteRepo] | None, *,
              reachable: Callable[[LocalRepo], bool] | None = None) -> Buckets:
    """Sort what was found into spec 4.7's four buckets.

    `linked` pairs a local repository with its listing entry, or with `None`
    when its origin is outside the listing but answers: the listing covers only
    the account's own repositories, so a colleague's is not stale. Only an origin
    missing from the listing is probed, because probing is a network call.
    """
    probe = reachable or _ls_remote
    by_key = {repo["key"]: repo for repo in remote or [] if repo.get("key")}
    buckets: Buckets = {"linked": [], "local_only": [], "remote_only": [], "stale": []}
    claimed: set[str] = set()

    for repo in local:
        if not repo.get("origin"):
            buckets["local_only"].append(repo)
        elif repo.get("key") in by_key:
            buckets["linked"].append((repo, by_key[repo["key"]]))
            claimed.add(repo["key"])
        elif probe(repo):
            buckets["linked"].append((repo, None))
        else:
            buckets["stale"].append(repo)

    buckets["remote_only"] = [repo for key, repo in by_key.items() if key not in claimed]
    return buckets


def _ls_remote(repo: LocalRepo) -> bool:
    """Does `origin` answer? Exit 2 is an empty repository, which still exists."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        completed = subprocess.run(
            ["git", "-C", repo["path"], "ls-remote", "--exit-code", "--heads", "origin"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=LS_REMOTE_TIMEOUT, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode in (0, 2)


# --- the stack guess ---------------------------------------------------------

def guess_profile(path: Path | str) -> str | None:
    """A catalogue profile this repository looks like, or `None`.

    Shown for correction, never applied silently (spec 4.7 round 3).
    """
    repo = Path(path)
    manifests = " ".join(
        _read(repo / name).lower()
        for name in ("requirements.txt", "requirements-dev.txt", "pyproject.toml",
                     "setup.py", "setup.cfg", "Pipfile")
    )
    entry_points = _read(repo / "app.py") + _read(repo / "wsgi.py")
    if re.search(r"\bflask\b", manifests) or re.search(
            r"^\s*(from flask import|import flask)", entry_points, re.M):
        return "flask-sqlite"
    if list(repo.glob("*.spec")) or "pyinstaller" in manifests:
        return "python-packaged"
    if any((repo / name).is_file() for name in ("pyproject.toml", "setup.py")):
        return "python-packaged"
    if (repo / "index.html").is_file():
        return "static-site"
    return None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# --- palettes and brand assets -----------------------------------------------

def palette(path: Path | str) -> dict[str, str]:
    """The repository's `:root` tokens, values normalised so equal compares equal.

    Vendored and minified stylesheets are skipped: Bootstrap's own `--bs-*`
    variables would otherwise make every Bootstrap project look like one brand.
    """
    tokens: dict[str, str] = {}
    for css in _files(Path(path), lambda p: p.suffix.lower() == ".css"
                      and not p.name.lower().endswith(".min.css")):
        for name, value in brands.tokens_in(_read(css)).items():
            tokens[name] = _normalise_value(value)
    return tokens


def _normalise_value(value: str) -> str:
    return re.sub(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b",
                  lambda m: brands.normalise_hex(m.group(0)), value.strip())


def cluster_palettes(palettes: Mapping[str, Mapping[str, str]]) -> list[dict[str, Any]]:
    """Repositories grouped by identical palette; the tokenless ones last.

    Largest group first: the palette most projects share is the likeliest brand.
    """
    groups: list[dict[str, Any]] = []
    empty: list[str] = []
    for name in palettes:
        tokens = dict(palettes[name])
        if not tokens:
            empty.append(name)
            continue
        for group in groups:
            if group["tokens"] == tokens:
                group["repos"].append(name)
                break
        else:
            groups.append({"tokens": tokens, "repos": [name]})
    groups.sort(key=lambda group: -len(group["repos"]))       # stable: first seen wins ties
    if empty:
        groups.append({"tokens": {}, "repos": empty})
    return groups


def brand_assets(path: Path | str) -> dict[str, list[str]]:
    """Candidate logos, favicons and brand guides, as repo-relative paths."""
    repo = Path(path)
    found: dict[str, list[str]] = {"logos": [], "favicons": [], "guides": []}
    for file in _files(repo, lambda p: True):
        stem, suffix = file.stem.lower(), file.suffix.lower()
        relative = file.relative_to(repo).as_posix()
        if stem.startswith("logo"):
            found["logos"].append(relative)
        elif stem.startswith("favicon"):
            found["favicons"].append(relative)
        elif suffix == ".pdf" and any(word in stem for word in GUIDE_WORDS):
            found["guides"].append(relative)
    return {key: sorted(value) for key, value in found.items()}


def _files(root: Path, keep: Callable[[Path], bool]) -> list[Path]:
    out: list[Path] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
        for name in sorted(files):
            candidate = Path(current) / name
            if keep(candidate):
                out.append(candidate)
    return out
