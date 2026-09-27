"""gitio.py — the only writer of the `main`-side files (spec 7.3, plan chunk 6).

Every repository here is a real one. Mocking git would test the mock, and the
three behaviours that matter most — no-remote mode, a rebase of a diverged
`main`, and a push that fails without losing the transition — are properties of
git itself, not of Taller's argument lists.

Every commit these tests make passes `-c user.name` / `-c user.email` so nothing
depends on the machine's git identity, and `-c commit.gpgsign=false` so a signing
configuration cannot hang the suite on a passphrase prompt. The same three are
written into each fixture repository's own config, because the commits gitio makes
are gitio's and carry no `-c` flags of their own.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import support

from taller import gitio, locking, paths
from taller.errors import GitError

IDENTITY = [
    "-c", "user.name=Taller Test",
    "-c", "user.email=test@example.invalid",
    "-c", "commit.gpgsign=false",
]

STATUS = ".taller/work/0001-demo/status.yml"
TOKENS = "static/css/tokens.css"          # flask-sqlite's paths.brand_tokens


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        ["git", *IDENTITY, "-C", str(cwd), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert completed.returncode == 0, (
        f"git {' '.join(args)} failed in {cwd}: {completed.stderr or completed.stdout}"
    )
    return completed


def git_bytes(cwd: Path, *args: str) -> bytes:
    """Raw stdout. `text=True` would translate newlines and void the LF test."""
    completed = subprocess.run(["git", *IDENTITY, "-C", str(cwd), *args],
                               capture_output=True)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def subjects(cwd: Path, ref: str = "main") -> list[str]:
    return git(cwd, "log", "--format=%s", ref).stdout.splitlines()


def on_main(cwd: Path, relative: str) -> bytes:
    """What `main` holds for a path - the invariant that matters, wherever Taller
    happened to write it from."""
    return git_bytes(cwd, "cat-file", "blob", f"main:{relative}")


def commit_all(cwd: Path, message: str) -> None:
    git(cwd, "add", "-A")
    git(cwd, "commit", "--quiet", "-m", message)


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    assert subprocess.run(
        ["git", "init", "--quiet", "-b", "main", str(path)],
        capture_output=True,
    ).returncode == 0
    git(path, "config", "user.name", "Taller Test")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "commit.gpgsign", "false")
    return path


def init_bare(path: Path) -> Path:
    assert subprocess.run(
        ["git", "init", "--quiet", "--bare", "-b", "main", str(path)],
        capture_output=True,
    ).returncode == 0
    return path


def move_origin(bare: Path, clone: Path, relative: str, text: str, message: str) -> None:
    """Someone else pushes to `origin/main`, so the local `main` falls behind."""
    assert subprocess.run(
        ["git", "clone", "--quiet", "-b", "main", str(bare), str(clone)],
        capture_output=True,
    ).returncode == 0
    git(clone, "config", "user.name", "Somebody Else")
    git(clone, "config", "user.email", "else@example.invalid")
    support.write(clone / relative, text)
    commit_all(clone, message)
    git(clone, "push", "--quiet", "origin", "main")


@pytest.fixture
def project(tmp_home) -> Path:
    """A registered `flask-sqlite` project that is a real repo with one commit."""
    path = support.make_project(name="demo", profile="flask-sqlite")
    init_repo(path)
    support.write(path / "app.py", "print('hello')\n")
    commit_all(path, "initial commit")
    return path


@pytest.fixture
def on_branch(project: Path) -> Path:
    """The same project with the owner on a ticket branch - the normal flow, where
    Taller writes through its own detached worktree rather than the owner's
    checkout."""
    git(project, "checkout", "--quiet", "-b", "ticket/0001")
    return project


@pytest.fixture
def remote(project: Path, tmp_path: Path) -> Path:
    """The same project, with a bare repository as `origin` and `main` pushed."""
    bare = init_bare(tmp_path / "origin.git")
    git(project, "remote", "add", "origin", str(bare))
    git(project, "push", "--quiet", "origin", "main")
    return bare


@pytest.fixture
def git_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record every git invocation, then delegate. A spy, not a stub."""
    calls: list[list[str]] = []
    original = gitio._git

    def spy(cwd, *args, **kwargs):
        calls.append(list(args))
        return original(cwd, *args, **kwargs)

    monkeypatch.setattr(gitio, "_git", spy)
    return calls


# --- invariant 1: idempotent, and returns the worktree path ------------------

def test_ensure_main_worktree_is_idempotent_and_returns_the_path(project: Path):
    first = gitio.ensure_main_worktree(project)
    second = gitio.ensure_main_worktree(project)

    assert first == second == paths.main_worktree("demo")
    assert (first / "app.py").is_file()
    assert git(project, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"

    registered = git(project, "worktree", "list", "--porcelain").stdout
    assert registered.count(str(first).replace("\\", "/")) == 1


# --- invariant 2: it requires at least one commit, and says so --------------

def test_ensure_main_worktree_requires_at_least_one_commit(tmp_home):
    path = support.make_project(name="fresh", profile="flask-sqlite")
    init_repo(path)                      # git init, and nothing committed

    with pytest.raises(GitError) as raised:
        gitio.ensure_main_worktree(path)

    message = str(raised.value)
    assert "no commits" in message
    assert "project new" in message      # names the command that must go first
    assert not paths.main_worktree("fresh").exists()


def test_ensure_main_worktree_requires_a_repository_at_all(tmp_home):
    path = support.make_project(name="bare", profile="flask-sqlite")

    with pytest.raises(GitError, match="not a git repository"):
        gitio.ensure_main_worktree(path)


# --- invariant 3: outside the project tree and outside the hub --------------

def test_the_worktree_is_outside_the_project_and_the_hub(project: Path):
    worktree = gitio.ensure_main_worktree(project)

    assert not worktree.is_relative_to(project)
    assert not worktree.is_relative_to(paths.hub())
    assert worktree.is_relative_to(paths.run_dir())
    assert not paths.run_dir().is_relative_to(paths.hub())


# --- invariant 4: only spec 7.2's paths, and it raises on anything else -----

ALLOWED = [
    ".taller/work/0001-demo/ticket.md",
    ".taller/work/0001-demo/status.yml",
    ".taller/work/0001-demo/notes.md",
    ".taller/work/0001-demo/rejected/2026-09-27T10-00-00/security.md",
    ".taller/resolved.json",
    ".taller/constitution/00-index.md",
    ".gitattributes",
    ".taller/queue.yml",                        # emptied by `ticket new --from-queue`
]

REFUSED = [
    "app.py",                                   # application code
    "README.md",
    ".taller/taller.yml",
    ".taller/work/0001-demo/plan.md",           # a branch file (spec 7.2)
    ".taller/work/0001-demo/gates/security.md",
    ".taller/work/0001-demo/rejected",          # the directory, not a file in it
    ".taller/work/status.yml",                  # no ticket folder
    "../elsewhere/status.yml",
    "/etc/passwd",
]


def test_commit_to_main_writes_every_path_on_the_allowed_list(project: Path):
    payload = {relative: f"# {relative}\n" for relative in ALLOWED}

    assert gitio.commit_to_main(project, payload, "everything allowed") == gitio.SYNC_LOCAL

    for relative in ALLOWED:
        assert on_main(project, relative) == f"# {relative}\n".encode()
    tracked = git(project, "ls-tree", "-r", "--name-only", "main").stdout.splitlines()
    assert set(ALLOWED) <= set(tracked)


@pytest.mark.parametrize("relative", REFUSED)
def test_commit_to_main_raises_on_a_path_off_the_allowed_list(project: Path, relative: str):
    with pytest.raises(GitError) as raised:
        gitio.commit_to_main(project, {relative: "x\n"}, "should never land")

    assert "programming error" in str(raised.value) or "relative" in str(raised.value)
    assert subjects(project) == ["initial commit"]


def test_commit_to_main_refuses_the_whole_write_when_one_path_is_off_the_list(project: Path):
    with pytest.raises(GitError):
        gitio.commit_to_main(
            project, {".taller/resolved.json": "{}\n", "app.py": "evil\n"}, "mixed",
        )

    assert subjects(project) == ["initial commit"]
    assert not paths.main_worktree("demo").exists()   # nothing was even prepared


def test_the_brand_tokens_path_comes_from_the_profile(tmp_home, project: Path):
    """flask-sqlite allows static/css/tokens.css; python-packaged has no brand."""
    assert gitio.brand_tokens_path(project) == TOKENS
    assert gitio.commit_to_main(project, {TOKENS: ":root {}\n"}, "tokens") == gitio.SYNC_LOCAL

    packaged = support.make_project(name="lib", profile="python-packaged")
    init_repo(packaged)
    support.write(packaged / "pyproject.toml", "[project]\nname = 'lib'\n")
    commit_all(packaged, "initial commit")

    assert gitio.brand_tokens_path(packaged) is None
    with pytest.raises(GitError, match="programming error"):
        gitio.commit_to_main(packaged, {"tokens.css": ":root {}\n"}, "no brand here")


# --- invariant 5: no-remote mode -------------------------------------------

def test_no_remote_is_sync_local_and_neither_fetches_nor_pushes(project: Path, git_calls):
    state = gitio.commit_to_main(project, {STATUS: "stage: plan\n"}, "status: plan")

    assert state == gitio.SYNC_LOCAL
    assert [call[0] for call in git_calls if call[0] in {"fetch", "push"}] == []
    assert subjects(project) == ["status: plan", "initial commit"]


# --- invariant 6: a remote and a clean fast-forward ------------------------

def test_a_clean_fast_forward_is_sync_ok(project: Path, remote: Path, git_calls):
    state = gitio.commit_to_main(project, {STATUS: "stage: plan\n"}, "status: plan")

    assert state == gitio.SYNC_OK
    assert "fetch" in [call[0] for call in git_calls]
    assert subjects(remote) == ["status: plan", "initial commit"]


# --- invariant 7: a moved origin/main is rebased and retried once ----------

def test_a_diverged_main_is_rebased_onto_the_remote_and_lands(
    project: Path, remote: Path, tmp_path: Path, git_calls,
):
    """Owner on a branch: Taller owns the integration there, so it may rebase."""
    move_origin(remote, tmp_path / "elsewhere", "b.txt", "moved\n", "somebody else")
    # An owner commit made on `main` earlier; then they move to a ticket branch. A
    # fast-forward is therefore refused from both sides at once.
    support.write(project / "owner.txt", "owner\n")
    commit_all(project, "owner work")
    git(project, "checkout", "--quiet", "-b", "ticket/0001")

    state = gitio.commit_to_main(project, {STATUS: "stage: build\n"}, "status: build")

    assert state == gitio.SYNC_OK
    assert "rebase" in [call[0] for call in git_calls]
    assert subjects(remote) == [
        "status: build", "owner work", "somebody else", "initial commit",
    ]


def test_a_generated_file_conflict_is_resolved_by_rewriting_it(
    project: Path, remote: Path, tmp_path: Path, git_calls,
):
    """paths.brand_tokens is the one allowed path inside the application's tree,
    so it is the one that can collide. It is generated, so spec 4.6 resolves the
    collision by discarding both sides — never by merging it.

    Owner on a branch, the path on which Taller may integrate at all."""
    git(project, "checkout", "--quiet", "-b", "ticket/0001")
    git(project, "remote", "set-url", "origin", str(tmp_path / "nowhere.git"))
    assert gitio.commit_to_main(project, {TOKENS: ":root { --a: 1; }\n"},
                                "tokens: first") == gitio.SYNC_PENDING

    git(project, "remote", "set-url", "origin", str(remote))
    move_origin(remote, tmp_path / "elsewhere", TOKENS, ":root { --a: 9; }\n",
                "their tokens")

    state = gitio.commit_to_main(
        project, {TOKENS: ":root { --a: 2; }\n", STATUS: "stage: plan\n"},
        "tokens: second",
    )

    assert state == gitio.SYNC_OK
    assert "rebase" in [call[0] for call in git_calls]
    assert git_bytes(remote, "cat-file", "blob", f"main:{TOKENS}") == b":root { --a: 2; }\n"
    assert "tokens: first" in subjects(remote)      # the earlier commit survived
    assert subjects(remote)[0] == "tokens: second"


# --- invariant 8: a failed push degrades, and loses no transition ----------

def test_a_failed_push_stays_local_as_sync_pending(project: Path, tmp_path: Path):
    git(project, "remote", "add", "origin", str(tmp_path / "nowhere.git"))

    state = gitio.commit_to_main(project, {STATUS: "stage: plan\n"}, "status: plan")

    assert state == gitio.SYNC_PENDING
    assert subjects(project) == ["status: plan", "initial commit"]
    assert on_main(project, STATUS) == b"stage: plan\n"
    # Nothing left half-written: the transition is committed, only unpushed.
    assert git(project, "status", "--porcelain").stdout.strip() == ""


def test_the_next_call_retries_the_push_and_loses_no_transition(
    project: Path, tmp_path: Path,
):
    bare = init_bare(tmp_path / "origin.git")
    git(project, "remote", "add", "origin", str(tmp_path / "nowhere.git"))

    assert gitio.commit_to_main(project, {STATUS: "stage: plan\n"},
                                "status: plan") == gitio.SYNC_PENDING

    git(project, "remote", "set-url", "origin", str(bare))
    assert gitio.commit_to_main(project, {STATUS: "stage: build\n"},
                                "status: build") == gitio.SYNC_OK

    # Both transitions are on the remote, in order. Neither was lost or squashed.
    assert subjects(bare) == ["status: build", "status: plan", "initial commit"]


# --- invariant 9: atomic replace, under the project lock ------------------

def test_every_write_is_an_atomic_replace_under_the_project_lock(
    project: Path, monkeypatch: pytest.MonkeyPatch,
):
    seen: list[tuple[str, bool]] = []
    original = locking.atomic_write

    def spy(target, data):
        seen.append((Path(target).name, locking.held(paths.project_lock("demo"))))
        return original(target, data)

    monkeypatch.setattr(locking, "atomic_write", spy)

    gitio.commit_to_main(
        project, {STATUS: "stage: plan\n", ".taller/resolved.json": "{}\n"}, "two files",
    )

    assert sorted(name for name, _ in seen) == ["resolved.json", "status.yml"]
    assert all(under_lock for _, under_lock in seen), (
        "a main-side write happened outside the project lock (spec 10.3)"
    )
    assert not locking.held(paths.project_lock("demo"))      # and it was released


# --- invariant 10: LF, whatever the platform -----------------------------

def test_writes_are_lf_whatever_the_platform(project: Path):
    notes = ".taller/work/0001-demo/notes.md"

    gitio.commit_to_main(project, {notes: "alpha\r\nbeta\r\n", STATUS: b"stage: plan\r\n"},
                         "crlf in, lf out")

    # The index is what spec 4.6's byte comparison reads back.
    assert on_main(project, notes) == b"alpha\nbeta\n"
    assert on_main(project, STATUS) == b"stage: plan\n"


# --- the consequence of two worktrees sharing one branch ref -------------

def test_a_commit_in_the_projects_own_checkout_is_never_reverted(project: Path):
    """An owner commit on `main` must survive the next Taller write. An earlier
    design shared the branch ref between two worktrees, where this failed unless
    every commit opened with `reset --hard`."""
    gitio.ensure_main_worktree(project)
    support.write(project / "owner.txt", "owner\n")
    commit_all(project, "owner work")

    gitio.commit_to_main(project, {".taller/resolved.json": "{}\n"}, "resolve")

    tracked = git(project, "ls-tree", "-r", "--name-only", "main").stdout.splitlines()
    assert "owner.txt" in tracked
    assert "app.py" in tracked
    assert ".taller/resolved.json" in tracked



# --- the redesign: main is never shared between two worktrees -----------------
#
# An earlier design checked `main` out in Taller's worktree with --force, so the
# owner's checkout and Taller's shared one branch ref. That was a data-loss bug in
# BOTH directions. These tests pin down each direction, in each place the owner
# can be.


def test_the_owners_commit_on_main_does_not_delete_tallers_file(project: Path):
    """The mirror-image bug. The owner, sitting on `main`, makes one ordinary
    commit of their own work. It must not carry away Taller's file.

    Verified broken under the old design: the owner's index held a staged deletion
    of `.taller/resolved.json`, and their next commit - any commit - deleted it,
    taking the rules snapshot with it."""
    assert gitio._current_branch(project) == "main"

    gitio.commit_to_main(project, {".taller/resolved.json": "{}\n"}, "taller: resolve")
    assert git(project, "status", "--porcelain").stdout.strip() == "", (
        "Taller's write left the owner's checkout showing a change"
    )

    support.write(project / "mine.txt", "my work\n")
    git(project, "add", "mine.txt")
    git(project, "commit", "--quiet", "-m", "owner: my work")

    tracked = git(project, "ls-tree", "-r", "--name-only", "main").stdout.splitlines()
    assert ".taller/resolved.json" in tracked, "the owner's commit deleted Taller's file"
    assert "mine.txt" in tracked


def test_tallers_write_on_main_leaves_the_owners_work_exactly_as_it_was(project: Path):
    """`commit --only`: a commit of exactly Taller's paths. The owner's staged and
    unstaged work is neither committed nor disturbed."""
    support.write(project / "staged.txt", "staged\n")
    git(project, "add", "staged.txt")
    support.write(project / "app.py", "print('an unstaged edit')\n")

    gitio.commit_to_main(project, {STATUS: "stage: plan\n"}, "status: plan")

    changed = git(project, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert changed == [STATUS], f"Taller's commit carried the owner's work: {changed}"
    status = git(project, "status", "--porcelain").stdout
    assert "A  staged.txt" in status, "the owner's staged file was disturbed"
    assert " M app.py" in status, "the owner's unstaged edit was disturbed"
    # And Taller's own file must not appear at all. Under the shared-ref design it
    # showed here as a staged deletion - the state the owner's next commit then
    # carried to main. Checking only that the owner's work survived missed that.
    assert STATUS not in status, (
        f"Taller's file appears in the owner's status, which means their next "
        f"commit will change it:\n{status}"
    )


def test_on_a_branch_taller_uses_a_detached_worktree_and_advances_main(on_branch: Path):
    """The normal ticket flow. Nothing of the owner's checkout is touched, and
    `main` gets the commit."""
    state = gitio.commit_to_main(on_branch, {STATUS: "stage: build\n"}, "status: build")

    assert state == gitio.SYNC_LOCAL
    assert on_main(on_branch, STATUS) == b"stage: build\n"
    assert gitio._current_branch(on_branch) == "ticket/0001", "the owner was moved"
    worktree = paths.main_worktree("demo")
    head = git(worktree, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert head == "HEAD", "Taller's worktree holds a branch; it must stay detached"


def test_the_owner_can_check_out_main_while_tallers_worktree_exists(on_branch: Path):
    """A worktree holding `main` would make git refuse this outright."""
    gitio.commit_to_main(on_branch, {STATUS: "stage: build\n"}, "status: build")
    git(on_branch, "checkout", "--quiet", "main")
    assert gitio._current_branch(on_branch) == "main"
    assert git(on_branch, "status", "--porcelain").stdout.strip() == "", (
        "the owner arrived on main to find Taller's files looking deleted"
    )


def test_a_worktree_from_an_earlier_version_is_detached_on_next_use(on_branch: Path):
    """Earlier installs checked `main` out here with --force. The next use must
    release it rather than need a manual step."""
    worktree = paths.main_worktree("demo")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    git(on_branch, "worktree", "add", "--quiet", "--force", str(worktree), "main")
    assert git(worktree, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"

    gitio.ensure_main_worktree(on_branch)

    assert git(worktree, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "HEAD"


def test_main_moving_mid_write_is_pending_and_the_owners_commit_survives(
    on_branch: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Compare-and-swap. If `main` moves after Taller based its work on it, the
    swap must fail - otherwise the owner's commit is silently overwritten."""
    original = gitio._integrate_remote
    owner_sha = {}

    def owner_commits_meanwhile(worktree, payload):
        git(on_branch, "checkout", "--quiet", "main")
        support.write(on_branch / "racing.txt", "owner, mid-write\n")
        commit_all(on_branch, "owner: racing commit")
        owner_sha["sha"] = git(on_branch, "rev-parse", "main").stdout.strip()
        git(on_branch, "checkout", "--quiet", "ticket/0001")
        return original(worktree, payload)

    # A remote that cannot be reached, so the integration hook runs mid-write; the
    # compare-and-swap is what is under test.
    git(on_branch, "remote", "add", "origin", str(on_branch.parent / "nowhere.git"))
    monkeypatch.setattr(gitio, "_integrate_remote", owner_commits_meanwhile)

    state = gitio.commit_to_main(on_branch, {STATUS: "stage: build\n"}, "status: build")

    assert state == gitio.SYNC_PENDING
    assert git(on_branch, "rev-parse", "main").stdout.strip() == owner_sha["sha"], (
        "the owner's racing commit was overwritten"
    )


def test_on_main_a_moved_remote_is_pending_and_the_branch_is_not_rewritten(
    project: Path, remote: Path, tmp_path: Path, git_calls,
):
    """The owner is on `main`, so integrating would rewrite or merge the branch
    under them. Taller commits locally and reports pending instead."""
    move_origin(remote, tmp_path / "elsewhere", "b.txt", "moved\n", "somebody else")
    support.write(project / "owner.txt", "owner\n")
    commit_all(project, "owner work")
    before = git(project, "log", "--format=%H", "main").stdout.splitlines()

    state = gitio.commit_to_main(project, {STATUS: "stage: plan\n"}, "status: plan")

    assert state == gitio.SYNC_PENDING
    assert not [c for c in git_calls if c[0] in {"rebase", "merge"}], (
        "Taller rebased or merged the owner's branch"
    )
    after = git(project, "log", "--format=%H", "main").stdout.splitlines()
    assert after[1:] == before, "the owner's existing history was rewritten"
    assert subjects(project)[0] == "status: plan"


def test_on_main_uncommitted_changes_to_our_path_are_never_overwritten(project: Path):
    """Recording nothing is better than destroying work."""
    gitio.commit_to_main(project, {STATUS: "stage: plan\n"}, "status: plan")
    support.write(project / STATUS, "stage: hand-edited by the owner\n")

    with pytest.raises(GitError, match="uncommitted changes"):
        gitio.commit_to_main(project, {STATUS: "stage: build\n"}, "status: build")

    assert (project / STATUS).read_text(encoding="utf-8") == (
        "stage: hand-edited by the owner\n"
    ), "the owner's uncommitted edit was overwritten"


def test_on_main_a_merge_in_progress_is_refused(project: Path):
    """A commit now would land inside the owner's merge rather than beside it."""
    git(project, "checkout", "--quiet", "-b", "side")
    support.write(project / "app.py", "print('side')\n")
    commit_all(project, "side")
    git(project, "checkout", "--quiet", "main")
    support.write(project / "app.py", "print('main')\n")
    commit_all(project, "main")
    subprocess.run(["git", *IDENTITY, "-C", str(project), "merge", "side"],
                   capture_output=True)                        # conflicts, deliberately
    assert (project / ".git" / "MERGE_HEAD").exists()

    with pytest.raises(GitError, match="merge"):
        gitio.commit_to_main(project, {STATUS: "stage: plan\n"}, "status: plan")
