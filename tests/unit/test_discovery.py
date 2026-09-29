"""discovery.py — find projects and brands on disk and on GitHub (spec 4.7).

Discovery proposes; `taller setup` round 6 is where anything gets written. So
every function here is a read, and the last test proves it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import support
from taller import discovery


def init_repo(path: Path, origin: str | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    if origin:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", origin], check=True)
    return path


# --- scan_roots --------------------------------------------------------------

def test_repositories_are_found_with_their_origin(tmp_path: Path):
    init_repo(tmp_path / "root" / "alpha", "git@github.com:someone/Alpha.git")
    init_repo(tmp_path / "root" / "group" / "beta")

    found = discovery.scan_roots([tmp_path / "root"])

    assert [(repo["name"], repo["key"]) for repo in found] == [
        ("alpha", "github.com/someone/alpha"),
        ("beta", None),
    ]
    assert found[1]["origin"] is None


def test_the_scan_does_not_descend_into_repos_dependencies_or_hidden_dirs(tmp_path: Path):
    root = tmp_path / "root"
    init_repo(root / "app")
    init_repo(root / "app" / "vendored")                  # inside a repository
    init_repo(root / "node_modules" / "pkg")
    init_repo(root / "venv" / "src" / "thing")
    init_repo(root / ".cache" / "clone")

    names = [repo["name"] for repo in discovery.scan_roots([root])]

    assert names == ["app"]


def test_a_git_file_counts_as_a_repository(tmp_path: Path):
    worktree = tmp_path / "root" / "linked"
    support.write(worktree / ".git", "gitdir: /somewhere/else\n")

    assert [repo["name"] for repo in discovery.scan_roots([tmp_path / "root"])] == ["linked"]


def test_max_depth_is_respected(tmp_path: Path):
    init_repo(tmp_path / "root" / "a" / "b" / "deep")

    assert discovery.scan_roots([tmp_path / "root"], max_depth=2) == []
    assert len(discovery.scan_roots([tmp_path / "root"], max_depth=3)) == 1


def test_a_missing_root_is_skipped_not_fatal(tmp_path: Path):
    assert discovery.scan_roots([tmp_path / "nowhere"]) == []


# --- remote_key --------------------------------------------------------------

@pytest.mark.parametrize("url, key", [
    ("https://github.com/Someone/Repo.git", "github.com/someone/repo"),
    ("https://github.com/someone/repo/", "github.com/someone/repo"),
    ("git@github.com:someone/repo.git", "github.com/someone/repo"),
    ("ssh://git@github.com:22/someone/repo.git", "github.com/someone/repo"),
    ("https://user:ghp_SECRET@github.com/someone/repo.git", "github.com/someone/repo"),
    ("/srv/git/repo.git", None),
    ("", None),
])
def test_remote_urls_normalise_to_one_key(url: str, key: str | None):
    assert discovery.remote_key(url) == key


def test_credentials_in_an_origin_never_reach_the_report(tmp_path: Path):
    init_repo(tmp_path / "root" / "leaky", "https://me:ghp_SECRET@github.com/me/leaky.git")

    repo = discovery.scan_roots([tmp_path / "root"])[0]

    assert "ghp_SECRET" not in json.dumps(repo)
    assert repo["origin"] == "https://github.com/me/leaky.git"


# --- list_remote -------------------------------------------------------------

def test_listing_without_gh_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)

    listing, reason = discovery.list_remote()

    assert listing is None
    assert "gh" in reason


def test_listing_with_gh_unauthenticated_is_reported(monkeypatch: pytest.MonkeyPatch):
    failed = subprocess.CompletedProcess([], 1, "", "You are not logged into any GitHub hosts.\n")
    monkeypatch.setattr(discovery, "_run_gh", lambda args: failed)

    listing, reason = discovery.list_remote()

    assert listing is None
    assert "not logged" in reason


def test_listing_parses_gh_json(monkeypatch: pytest.MonkeyPatch):
    payload = json.dumps([
        {"nameWithOwner": "me/alpha", "url": "https://github.com/me/alpha", "isPrivate": True},
    ])
    ok = subprocess.CompletedProcess([], 0, payload, "")
    monkeypatch.setattr(discovery, "_run_gh", lambda args: ok)

    listing, reason = discovery.list_remote()

    assert listing == [{"name": "me/alpha", "key": "github.com/me/alpha",
                        "url": "https://github.com/me/alpha", "private": True}]
    assert reason == ""


# --- reconcile ---------------------------------------------------------------

def local(name: str, origin: str | None) -> dict:
    return {"path": f"/p/{name}", "name": name, "origin": origin,
            "key": discovery.remote_key(origin) if origin else None}


def remote(full: str) -> dict:
    return {"name": full, "key": f"github.com/{full}", "url": f"https://github.com/{full}",
            "private": True}


def test_reconcile_sorts_into_the_four_buckets():
    repos = [
        local("linked", "https://github.com/me/linked"),
        local("lonely", None),
        local("renamed", "https://github.com/me/old-name"),
    ]
    listing = [remote("me/linked"), remote("me/never-cloned")]
    checked = []

    def reachable(repo):
        checked.append(repo["name"])
        return False

    buckets = discovery.reconcile(repos, listing, reachable=reachable)

    assert [(l["name"], r["name"]) for l, r in buckets["linked"]] == [("linked", "me/linked")]
    assert [repo["name"] for repo in buckets["local_only"]] == ["lonely"]
    assert [repo["name"] for repo in buckets["remote_only"]] == ["me/never-cloned"]
    assert [repo["name"] for repo in buckets["stale"]] == ["renamed"]
    assert checked == ["renamed"], "only an origin missing from the listing is probed"


def test_an_origin_outside_the_listing_that_resolves_is_not_stale():
    """The listing covers only the account's repositories; a colleague's is fine."""
    repos = [local("theirs", "https://github.com/colleague/theirs")]

    buckets = discovery.reconcile(repos, [], reachable=lambda repo: True)

    assert [(l["name"], r) for l, r in buckets["linked"]] == [("theirs", None)]
    assert buckets["stale"] == []


def test_without_a_listing_every_origin_is_probed():
    repos = [local("up", "https://github.com/me/up"), local("down", "https://github.com/me/down")]

    buckets = discovery.reconcile(repos, None, reachable=lambda repo: repo["name"] == "up")

    assert [l["name"] for l, _ in buckets["linked"]] == ["up"]
    assert [repo["name"] for repo in buckets["stale"]] == ["down"]
    assert buckets["remote_only"] == []


# --- guess_profile -----------------------------------------------------------

@pytest.mark.parametrize("files, profile", [
    ({"requirements.txt": "Flask==3.0.3\n"}, "flask-sqlite"),
    ({"app.py": "from flask import Flask\n"}, "flask-sqlite"),
    ({"tool.spec": "# pyinstaller\n", "main.py": "print()\n"}, "python-packaged"),
    ({"pyproject.toml": "[project]\nname='x'\n"}, "python-packaged"),
    ({"index.html": "<!doctype html>\n"}, "static-site"),
    ({"notes.txt": "hello\n"}, None),
])
def test_the_stack_guess(tmp_path: Path, files: dict, profile: str | None):
    for name, text in files.items():
        support.write(tmp_path / "repo" / name, text)

    assert discovery.guess_profile(tmp_path / "repo") == profile


# --- palettes and brands -----------------------------------------------------

def test_palette_reads_root_tokens_normalised_skipping_vendored_css(tmp_path: Path):
    repo = tmp_path / "repo"
    support.write(repo / "static" / "css" / "site.css",
                  ":root { --color-primary: #1B365D; --gap: 8px; }")
    support.write(repo / "static" / "css" / "bootstrap.min.css", ":root { --bs-blue: #0d6efd; }")
    support.write(repo / "node_modules" / "x" / "x.css", ":root { --x: #fff; }")

    assert discovery.palette(repo) == {"--color-primary": "#1b365d", "--gap": "8px"}


def test_identical_palettes_cluster_and_tokenless_repos_group_apart():
    palettes = {
        "a": {"--color-primary": "#1b365d"},
        "b": {"--color-primary": "#1b365d"},
        "c": {"--color-primary": "#223344"},
        "d": {},
    }

    clusters = discovery.cluster_palettes(palettes)

    assert [cluster["repos"] for cluster in clusters] == [["a", "b"], ["c"], ["d"]]
    assert clusters[-1]["tokens"] == {}


def test_brand_assets_are_located(tmp_path: Path):
    repo = tmp_path / "repo"
    for name in ("static/img/logo.svg", "static/favicon.ico", "docs/Brand Guidelines.pdf",
                 "docs/invoice.pdf", "node_modules/x/logo.png"):
        support.write(repo / name, "x")

    assets = discovery.brand_assets(repo)

    assert assets == {
        "logos": ["static/img/logo.svg"],
        "favicons": ["static/favicon.ico"],
        "guides": ["docs/Brand Guidelines.pdf"],
    }


# --- discovery writes nothing ------------------------------------------------

def test_discovery_writes_nothing(tmp_path: Path):
    root = tmp_path / "root"
    repo = init_repo(root / "site", "https://github.com/me/site")
    support.write(repo / "index.html", "<!doctype html>\n")
    support.write(repo / "styles.css", ":root { --a: #fff; }")
    support.write(repo / "logo.png", "x")
    before = support.tree_mtimes(tmp_path)

    found = discovery.scan_roots([root])
    discovery.guess_profile(repo)
    discovery.cluster_palettes({r["name"]: discovery.palette(Path(r["path"])) for r in found})
    discovery.brand_assets(repo)

    assert support.tree_mtimes(tmp_path) == before
