# Taller Phase A Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `taller project new` creates a working project from an empty hub, and `taller doctor` passes every check Phase A provides.

**Architecture:** A standalone Python package. `inference.py` is the only module that spawns the `claude` CLI; `constitution.py` resolves configuration and renders three generated artefacts; `gitio.py` is the only writer of `main`-side files. Every module is pure over its arguments or pure over the filesystem, so the whole phase is unit-testable without a single real inference call.

**Tech Stack:** Python 3.11, pytest, PyYAML, pypdf, pillow, the `claude` CLI (2.1.74 verified), `gh` (optional in this phase).

**Spec:** [2026-09-26-taller-design.md](../specs/2026-09-26-taller-design.md) — §10.4's Phase A row is the scope contract.

**Pilot:** a throwaway greenfield project created on an empty hub. Adoption of an existing repository is proved second.

---

## Scope

From §10.4's Phase A row, in dependency order:

| # | Component | Spec |
|---|---|---|
| 1 | CLI flag verification + `cli_min_version` | §3.4 |
| 2 | `locking.py` — re-entrant project / hub / registry locks | §10.3 |
| 3 | `HubConfig` + `load_hub_config()` | §4.4.1 |
| 4 | `registry.py` | §10.2 |
| 5 | `inference.py` — `Dispatch`/`Result`, bootstrap mode, `forbidden` rendering, cross-process concurrency | §3.6, §3.6.1, §3.6.2 |
| 6 | The catalogue — three profiles, modules, scaffolds | §4.0, §4.1 |
| 7 | `overrides.py` + the non-suppressible predicate | §4.5 |
| 8 | `constitution.py` — both chains, `resolve()`, three renderers | §4.3, §4.4, §4.6, §3.1, §4.2.1 |
| 9 | `gitio.py` — `main` worktree, `commit_to_main()`, no-remote mode | §7.3 |
| 10 | `brands.py` — `from_pdf()`, `from_css()`, `from_image()`, `swatch()` | §4.2 |
| 11 | `scaffold.py` — manifest rendering with omissions | §11.4 |
| 12 | `discovery.py` — disk + `gh` reconcile, palette clustering | §4.7 |
| 13 | `taller setup`, `project new`, `project adopt`, `project brief`, `settings`, `doctor` | §3.5, §4.7, §11 |
| 14 | The greenfield acceptance test | §15.5 |

**Explicitly not in this phase:** tickets, `status.yml`, stage transitions, gates, the cockpit, CI, staging. Answer ⑫ of the wizard lands as `queue.yml`; Phase D converts it (§11.4).

---

## File Structure

```
taller/
├── pyproject.toml                  console_script: taller = taller.cli:main
├── src/taller/
│   ├── __init__.py
│   ├── cli.py                      argument parsing ONLY; no logic
│   ├── errors.py                   TallerError hierarchy
│   ├── locking.py                  re-entrant file locks + atomic replace
│   ├── paths.py                    where everything lives (~/.taller, ~/.taller-run)
│   ├── config.py                   HubConfig, load_hub_config, deep merge
│   ├── registry.py                 ~/.taller/projects.json
│   ├── inference.py                THE only caller of `claude`
│   ├── overrides.py                parse, match, downgrade
│   ├── constitution.py             resolve() + render_snapshot/index/tokens
│   ├── gitio.py                    main worktree, commit_to_main
│   ├── brands.py                   from_pdf/from_css/from_image/write/swatch
│   ├── scaffold.py                 catalogue copy + manifest rendering
│   ├── discovery.py                disk/gh scan, palette clustering
│   ├── doctor.py                   checks with pass/fail/skip-with-reason
│   └── commands/                   one module per CLI verb; thin
│       ├── setup.py  project.py  brand.py  settings.py  doctor.py
│   └── catalogue/                  INSIDE the package, so a wheel ships it
│       ├── modules/                stack/ security/ conventions/ ux/ never.md
│       ├── profiles/               flask-sqlite.yml static-site.yml python-packaged.yml
│       └── scaffolds/<profile>/    manifest.yml + *.j2
└── tests/
    ├── conftest.py                 tmp HOME, stub `claude` on PATH
    ├── stub_claude.py              the fake CLI every inference test runs against
    ├── unit/                       one file per module
    ├── fixtures/                   sample repos, a brand-guide PDF, CSS palettes
    └── acceptance/test_greenfield.py   §15.5
```

**Why this split:** `cli.py` holds no logic so every verb is testable without argument parsing. `paths.py` exists so no other module hardcodes `~/.taller`, which is what makes the tmp-`HOME` test fixture work. `commands/` is thin because the library is the single implementation (§3.5) — a command module only collects input and calls the library.

---

## Conventions for every task

- **Language:** code, comments, identifiers, commit messages in English.
- **Commits:** `type(scope): summary` — `feat` `fix` `refactor` `chore` `docs` `test`.
- **TDD:** the failing test comes first, every time. Run it, see it fail, then implement.
- **No real inference in tests.** Every test that touches `inference.py` runs against `tests/stub_claude.py` placed on `PATH` by the fixture. A test suite that spends the owner's subscription window is a test suite nobody runs.

> **⚠ The one bug that would cost real money.** On Windows, `CreateProcess` appends only `.exe` to an extensionless name, so `subprocess.run(["claude", ...])` **skips a `claude.cmd` earlier on `PATH`** and runs the real `claude.exe` instead. Reproduced on this machine: `shutil.which("claude")` returned the stub shim while `subprocess.run(["claude","--version"])` printed `2.1.74` from the real binary. Every module that spawns the CLI — `inference.py` and `cli_probe.py` — must therefore **resolve the executable to an absolute path with `shutil.which()` and spawn that.** Without it, the whole inference suite makes real billed dispatches, empties nothing into the argv log, and fails on a confusing assertion.

Run the suite with:

```bash
python -m pytest -q
```

---

## Chunk 1: Skeleton, locking, paths

### Task 1: Repository skeleton and a green empty suite

**Files:**
- Create: `pyproject.toml`, `src/taller/__init__.py`, `src/taller/errors.py`, `tests/unit/test_smoke.py`
- Create (empty placeholders, filled in Chunk 4): `src/taller/catalogue/modules/.gitkeep`, `src/taller/catalogue/profiles/.gitkeep`, `src/taller/catalogue/scaffolds/.gitkeep`

**Note:** the catalogue lives **inside the package** at `src/taller/catalogue/`, not at the repository root. A root `templates/` directory would ship nothing in a wheel, since `packages.find` only collects from `src`. The placeholders exist from Task 1 so that Task 2's catalogue assertion is not a forward reference.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_smoke.py`:

```python
def test_package_imports():
    import taller
    assert taller.__version__
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_smoke.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'taller'`

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "taller"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["PyYAML>=6.0", "pypdf>=4.0", "pillow>=10.0"]

[project.optional-dependencies]
dev = ["pytest>=7.4"]

[project.scripts]
taller = "taller.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
"taller" = ["catalogue/**/*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 4: Write `src/taller/__init__.py`**

```python
"""Taller — a standalone program for running projects through an AI engineering team."""

__version__ = "0.1.0"
```

- [ ] **Step 5: Write `src/taller/errors.py`**

```python
"""The error hierarchy. Every failure Taller reports is one of these."""


class TallerError(Exception):
    """Base class. Carries a message meant for the owner, not a stack trace."""


class ConfigError(TallerError):
    """Configuration is missing, malformed, or contradictory."""


class LockTimeout(TallerError):
    """A lock could not be taken within its timeout."""


class InferenceError(TallerError):
    """A dispatch to the `claude` CLI failed."""


class GitError(TallerError):
    """A git operation failed."""


class DoctorFailure(TallerError):
    """A doctor check failed."""
```

- [ ] **Step 6: Install in editable mode and run the test**

```bash
mkdir -p src/taller/catalogue/modules src/taller/catalogue/profiles src/taller/catalogue/scaffolds
touch src/taller/catalogue/modules/.gitkeep src/taller/catalogue/profiles/.gitkeep src/taller/catalogue/scaffolds/.gitkeep
python -m pip install -e ".[dev]"
python -m pytest tests/unit/test_smoke.py -q
```

Expected: `1 passed`.

Two things to know about this step: it is **the only step that needs the network**, because `pypdf` is confirmed absent on this machine (`PyYAML` and `pillow` are already present); and the `taller` console script it installs will **traceback until Chunk 8**, because `cli.py` does not exist yet. That is expected, not a broken Task 1.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src tests
git commit -m "chore: package skeleton, error hierarchy, empty test suite"
```

---

### Task 2: `paths.py` — one place that knows where things live

**Files:**
- Create: `src/taller/paths.py`, `tests/unit/test_paths.py`, `tests/conftest.py`

**Why first:** every later test needs an isolated `HOME`. That only works if no module hardcodes a path (§4, §15.5 step 1).

- [ ] **Step 1: Write the failing test**

`tests/unit/test_paths.py`:

```python
from pathlib import Path

from taller import paths


def test_hub_is_under_home(tmp_home: Path):
    assert paths.hub() == tmp_home / ".taller"


def test_run_dir_is_separate_from_hub(tmp_home: Path):
    # Runtime state must NOT live inside the hub git repository (spec 3.2).
    assert paths.run_dir() == tmp_home / ".taller-run"
    assert paths.hub() not in paths.run_dir().parents


def test_named_subpaths(tmp_home: Path):
    assert paths.hub_config() == tmp_home / ".taller" / "taller.yml"
    assert paths.registry() == tmp_home / ".taller" / "projects.json"
    assert paths.brands() == tmp_home / ".taller" / "brands"
    assert paths.modules() == tmp_home / ".taller" / "modules"
    assert paths.profiles() == tmp_home / ".taller" / "profiles"
    assert paths.hub_lock() == tmp_home / ".taller-run" / ".lock"
    assert paths.registry_lock() == tmp_home / ".taller-run" / "registry.lock"
    assert paths.project_lock("demo") == tmp_home / ".taller-run" / "locks" / "demo.lock"
    assert paths.scratch_cwd() == tmp_home / ".taller-run" / "dispatch" / "scratch"
    assert paths.dispatch_slots() == tmp_home / ".taller-run" / "dispatch" / "slots"
    assert paths.main_worktree("demo") == tmp_home / ".taller-run" / "worktrees" / "demo-main"


def test_catalogue_ships_inside_the_package():
    # Inside the installed package, not in the hub and not at the repo root,
    # so a wheel ships it (spec 4.0).
    assert paths.catalogue().is_dir()
    assert paths.catalogue().parent.name == "taller"
    assert (paths.catalogue() / "profiles").is_dir()
```

- [ ] **Step 2: Write the `tmp_home` fixture**

`tests/conftest.py`:

```python
"""Shared fixtures. Every test runs against an isolated HOME."""

import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty HOME. No hub, no runtime state, nothing registered.

    This is the state a first-ever install is in, and the state spec 15.5
    requires the greenfield test to run against.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_VERTEX", raising=False)
    return home
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_paths.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'taller.paths'`

- [ ] **Step 4: Implement `paths.py`**

```python
"""Every filesystem location Taller uses.

No other module hardcodes a path. That is what lets the test suite run against
an isolated HOME, and what keeps runtime state out of the hub git repository
(spec 3.2).
"""

from pathlib import Path


def home() -> Path:
    return Path.home()


# --- the hub: a git repository, versioned content only -----------------------

def hub() -> Path:
    return home() / ".taller"


def hub_config() -> Path:
    return hub() / "taller.yml"


def registry() -> Path:
    return hub() / "projects.json"


def brands() -> Path:
    return hub() / "brands"


def modules() -> Path:
    return hub() / "modules"


def profiles() -> Path:
    return hub() / "profiles"


def models_probe() -> Path:
    return hub() / "models-probe.json"


# --- runtime state: never versioned, never inside the hub --------------------

def run_dir() -> Path:
    return home() / ".taller-run"


def hub_lock() -> Path:
    return run_dir() / ".lock"


def registry_lock() -> Path:
    return run_dir() / "registry.lock"


def project_lock(project_name: str) -> Path:
    return run_dir() / "locks" / f"{project_name}.lock"


def onboarding(name: str) -> Path:
    return run_dir() / "onboarding" / f"{name}.yml"


def main_worktree(project_name: str) -> Path:
    return run_dir() / "worktrees" / f"{project_name}-main"


def scratch_cwd() -> Path:
    """Working directory for a bootstrap dispatch.

    Deliberately empty: no CLAUDE.md and no .claude/, so a dispatch made before
    any project exists cannot inherit an arbitrary repository's briefing or
    hooks (spec 3.6).
    """
    return run_dir() / "dispatch" / "scratch"


def dispatch_slots() -> Path:
    """Cross-process concurrency semaphore (spec 3.6)."""
    return run_dir() / "dispatch" / "slots"


def smoke_dir(project_name: str, ticket_id: int) -> Path:
    return run_dir() / "smoke" / f"{project_name}-{ticket_id}"


# --- the catalogue: inside the installed package, inert until copied ---------

def catalogue() -> Path:
    """Inside the installed package, so a wheel ships it (spec 4.0)."""
    return Path(__file__).resolve().parent / "catalogue"


# --- per project -------------------------------------------------------------

def project_taller(project_path: Path) -> Path:
    return Path(project_path) / ".taller"


def project_config(project_path: Path) -> Path:
    return project_taller(project_path) / "taller.yml"


def project_constitution(project_path: Path) -> Path:
    return project_taller(project_path) / "constitution"


def project_snapshot(project_path: Path) -> Path:
    return project_taller(project_path) / "resolved.json"


def project_index(project_path: Path) -> Path:
    return project_constitution(project_path) / "00-index.md"


def project_queue(project_path: Path) -> Path:
    return project_taller(project_path) / "queue.yml"
```

- [ ] **Step 5: Run the test**

Run: `python -m pytest tests/unit/test_paths.py -q`
Expected: `4 passed`

- [ ] **Step 6: Commit**

```bash
git add src/taller/paths.py tests/conftest.py tests/unit/test_paths.py
git commit -m "feat(paths): single source of truth for every filesystem location"
```

---

### Task 3: `locking.py` — re-entrant, with atomic replace

**Files:**
- Create: `src/taller/locking.py`, `tests/unit/test_locking.py`

**Spec:** §10.3. Three locks, re-entrant within a process, 5-second timeout, atomic replace for every write.

**Why re-entrancy matters:** §7.6 holds the project lock for a whole chief dispatch, and a stage transition inside that window calls `commit_to_main()`, which takes the same lock. A non-re-entrant lock deadlocks against itself on the system's most common path.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_locking.py`:

```python
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from taller import locking
from taller.errors import LockTimeout


def test_lock_is_reentrant_within_a_process(tmp_path: Path):
    lock = tmp_path / "a.lock"
    with locking.file_lock(lock):
        with locking.file_lock(lock):  # must NOT deadlock — spec 10.3
            pass


def test_lock_releases_only_at_the_outermost_exit(tmp_path: Path):
    lock = tmp_path / "a.lock"
    with locking.file_lock(lock):
        with locking.file_lock(lock):
            pass
        assert locking.held(lock)  # inner exit must not release
    assert not locking.held(lock)


def test_second_process_times_out_and_the_file_survives(tmp_path: Path):
    lock = tmp_path / "a.lock"
    target = tmp_path / "data.txt"
    target.write_text("original", encoding="utf-8")

    ready = tmp_path / "ready"
    holder = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
            import pathlib, time
            from taller import locking
            with locking.file_lock({str(lock)!r}):
                pathlib.Path({str(ready)!r}).write_text("1")
                time.sleep(8)
        """)],
    )
    try:
        import time
        deadline = time.monotonic() + 20          # a readiness file, not a guessed sleep
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "holder process never acquired the lock"
        with pytest.raises(LockTimeout):
            with locking.file_lock(lock, timeout=5):
                target.write_text("clobbered", encoding="utf-8")
        assert target.read_text(encoding="utf-8") == "original"
    finally:
        holder.kill()
        holder.wait()


def test_a_non_reentrant_lock_refuses_the_same_thread(tmp_path: Path):
    """Semaphore slots must not be re-entrant, or a nested dispatch would exceed
    the concurrency cap silently."""
    lock = tmp_path / "slot-0.lock"
    with locking.file_lock(lock, reentrant=False):
        with pytest.raises(LockTimeout, match="semaphore slot"):
            with locking.file_lock(lock, timeout=0.1, reentrant=False):
                pass


def test_atomic_write_replaces_in_place(tmp_path: Path):
    target = tmp_path / "out.txt"
    locking.atomic_write(target, b"hello")
    assert target.read_bytes() == b"hello"
    locking.atomic_write(target, b"goodbye")
    assert target.read_bytes() == b"goodbye"
    # No temporary files left behind.
    assert [p.name for p in tmp_path.iterdir()] == ["out.txt"]


def test_atomic_write_creates_parent_directories(tmp_path: Path):
    target = tmp_path / "deep" / "nested" / "out.txt"
    locking.atomic_write(target, b"x")
    assert target.read_bytes() == b"x"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_locking.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'taller.locking'`

- [ ] **Step 3: Implement `locking.py`**

```python
"""File locks and atomic writes.

Locks are re-entrant within a process, because spec 7.6 holds the project lock
for a whole chief dispatch while a stage transition inside that window takes the
same lock through gitio.commit_to_main(). A non-re-entrant lock would deadlock
against itself on the most common path in the system.

Cross-process exclusion uses an exclusive create (O_EXCL), which is atomic on
both POSIX and Windows and needs no third-party dependency.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from pathlib import Path
from typing import Iterator

from . import paths
from .errors import LockTimeout

DEFAULT_TIMEOUT = 5.0
_POLL = 0.05

# lock path (resolved, as str) -> re-entrancy depth, per THREAD.
# Thread-local because the cockpit (spec 12) is a threaded server in one process,
# where a process-wide counter would let thread B believe it holds thread A's lock.
_state = threading.local()


def _depths() -> dict[str, int]:
    if not hasattr(_state, "depth"):
        _state.depth = {}
    return _state.depth


def held(lock_path: Path | str) -> bool:
    """True when this thread currently holds the lock. Reads without mutating."""
    return _depths().get(str(Path(lock_path).resolve()), 0) > 0


@contextlib.contextmanager
def file_lock(
    lock_path: Path | str,
    timeout: float = DEFAULT_TIMEOUT,
    reentrant: bool = True,
) -> Iterator[None]:
    """Hold an exclusive lock. Re-entrant within this thread by default.

    Raises LockTimeout rather than waiting indefinitely or forcing, so a stuck
    holder produces a clear message instead of a hang.

    `reentrant=False` is for counting semaphores. A re-entrant lock used as a
    semaphore silently stops capping: the second acquisition in the same thread
    succeeds by design, so a nested dispatch would exceed the concurrency limit
    without any error. Verified both ways before this was written.
    """
    path = Path(lock_path).resolve()
    key = str(path)
    depth = _depths()

    if depth.get(key, 0) > 0:      # already ours
        if not reentrant:
            raise LockTimeout(
                f"{path} is already held by this thread and was requested "
                f"non-re-entrantly. It is a semaphore slot, not a mutex."
            )
        depth[key] += 1             # just count deeper
        try:
            yield
        finally:
            depth[key] -= 1
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd = None
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise LockTimeout(
                    f"Could not take the lock at {path} within {timeout:g}s. "
                    f"Another Taller process is probably still working. "
                    f"If none is, remove the file."
                )
            time.sleep(_POLL)

    os.write(fd, str(os.getpid()).encode("ascii"))
    os.close(fd)
    depth[key] = 1
    try:
        yield
    finally:
        depth[key] = 0
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


# --- the three named locks of spec 10.2, as context managers ----------------

def hub_lock(timeout: float = DEFAULT_TIMEOUT):
    """Hub amendments."""
    return file_lock(paths.hub_lock(), timeout)


def registry_lock(timeout: float = DEFAULT_TIMEOUT):
    """projects.json writes."""
    return file_lock(paths.registry_lock(), timeout)


def project_lock(project_name: str, timeout: float = DEFAULT_TIMEOUT):
    """A project's main-side files, and a whole chief dispatch (spec 7.6)."""
    return file_lock(paths.project_lock(project_name), timeout)


def atomic_write(target: Path | str, data: bytes) -> None:
    """Write via a temporary file in the same directory, then os.replace.

    Same directory so the replace cannot cross a filesystem boundary, which is
    what makes it atomic.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp{os.getpid()}")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def atomic_write_text(target: Path | str, text: str) -> None:
    """Always UTF-8 with LF endings, so generated files are byte-stable across
    platforms — spec 4.6's tamper check compares bytes."""
    atomic_write(target, text.replace("\r\n", "\n").encode("utf-8"))
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/unit/test_locking.py -q`
Expected: `6 passed`. The cross-process test takes ~6 seconds; that is the timeout being proved.

- [ ] **Step 5: Commit**

```bash
git add src/taller/locking.py tests/unit/test_locking.py
git commit -m "feat(locking): re-entrant file locks and atomic writes"
```

---

### Task 4: CLI flag verification

**Files:**
- Create: `src/taller/cli_probe.py`, `tests/unit/test_cli_probe.py`

**Spec:** §3.4. This is the first thing Phase A builds, because every argument in §3.6's mapping table is an assumption about a binary whose defaults move (§3.6.2).

**Already verified on 2026-09-26 against `claude 2.1.74`:** twelve required flags present; `--permission-prompts` and `--bare` absent. The code must treat those two as optional.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_cli_probe.py`:

```python
from taller import cli_probe

HELP_WITH_EVERYTHING = """
  -p, --print
  --output-format <format>
  --json-schema <schema>
  --append-system-prompt <prompt>
  --resume [sessionId]
  --session-id <uuid>
  --add-dir <directories...>
  --allowedTools, --allowed-tools <tools...>
  --disallowedTools, --disallowed-tools <tools...>
  --agents <json>
  --model <model>
  --permission-mode <mode>
  --permission-prompts <mode>
  --bare
"""

HELP_AS_SHIPPED_ON_2_1_74 = HELP_WITH_EVERYTHING.replace(
    "  --permission-prompts <mode>\n", ""
).replace("  --bare\n", "")


def test_all_required_flags_present_passes():
    report = cli_probe.check_flags(HELP_AS_SHIPPED_ON_2_1_74)
    assert report.ok
    assert report.missing_required == []


def test_optional_flags_are_reported_but_do_not_fail():
    report = cli_probe.check_flags(HELP_AS_SHIPPED_ON_2_1_74)
    assert set(report.missing_optional) == {"--permission-prompts", "--bare"}
    assert report.ok


def test_a_missing_required_flag_fails():
    help_text = HELP_AS_SHIPPED_ON_2_1_74.replace("  --json-schema <schema>\n", "")
    report = cli_probe.check_flags(help_text)
    assert not report.ok
    assert report.missing_required == ["--json-schema"]


def test_version_is_parsed():
    assert cli_probe.parse_version("2.1.74 (Claude Code)") == (2, 1, 74)


def test_version_comparison():
    assert cli_probe.version_at_least((2, 1, 74), "2.1.74")
    assert cli_probe.version_at_least((2, 2, 0), "2.1.74")
    assert not cli_probe.version_at_least((2, 1, 73), "2.1.74")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_cli_probe.py -q`
Expected: FAIL — no module named `taller.cli_probe`

- [ ] **Step 3: Implement `cli_probe.py`**

```python
"""Verify the `claude` CLI's flag surface.

Spec 3.6's mapping table is a set of assumptions about a binary that changes
under us — spec 3.6.2 documents one flag that would silently break subscription
billing if it became a default. So the flags are checked, and the version is
recorded, rather than hoped for.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field

# Every flag spec 3.6's mapping table depends on.
REQUIRED_FLAGS = [
    "-p",
    "--output-format",
    "--json-schema",
    "--append-system-prompt",
    "--resume",
    "--session-id",
    "--add-dir",
    "--allowedTools",
    "--disallowedTools",
    "--agents",
    "--model",
    "--permission-mode",
]

# Used when present, omitted when not (spec 3.4).
OPTIONAL_FLAGS = [
    "--permission-prompts",   # needs 2.1.259+; dontAsk carries unattended alone
    "--bare",                 # absent on 2.1.74; spec 3.6.2's guard is forward-looking
]


@dataclass
class FlagReport:
    version: tuple[int, int, int] | None = None
    missing_required: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing_required

    def supports(self, flag: str) -> bool:
        return flag not in self.missing_optional and flag not in self.missing_required


def check_flags(help_text: str) -> FlagReport:
    report = FlagReport()
    for flag in REQUIRED_FLAGS:
        if not _mentions(help_text, flag):
            report.missing_required.append(flag)
    for flag in OPTIONAL_FLAGS:
        if not _mentions(help_text, flag):
            report.missing_optional.append(flag)
    return report


def _mentions(help_text: str, flag: str) -> bool:
    # Word boundary on the right so `-p` does not match `--print-foo`.
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", help_text) is not None


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        return None
    return tuple(int(g) for g in match.groups())  # type: ignore[return-value]


def version_at_least(version: tuple[int, int, int], minimum: str) -> bool:
    return version >= parse_version(minimum)  # type: ignore[operator]


def probe(executable: str = "claude") -> FlagReport:
    """Run the real binary. Used by `taller doctor`, never by unit tests."""
    from .errors import InferenceError

    # Resolve BEFORE spawning — the same rule as inference.py. On Windows a bare
    # name skips a .cmd shim earlier on PATH. Not billed here, but this is the
    # pattern inference.py is written from, where it is.
    resolved = shutil.which(executable)
    if resolved is None:
        raise InferenceError(
            f"The `{executable}` CLI is not on PATH. Taller performs every act of "
            f"inference through it (spec 3.6) and cannot work without it."
        )
    help_text = _run(resolved, "--help")      # checks returncode; see below
    version_text = _run(resolved, "--version")
    report = check_flags(help_text)
    report.version = parse_version(version_text)
    return report
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/unit/test_cli_probe.py -q`
Expected: `5 passed`

- [ ] **Step 5: Verify against the real binary and record what you see**

```bash
python -c "from taller import cli_probe; r=cli_probe.probe(); print('version', r.version); print('ok', r.ok); print('missing required', r.missing_required); print('missing optional', r.missing_optional)"
```

Expected on this machine: `version (2, 1, 74)`, `ok True`, `missing required []`, `missing optional ['--permission-prompts', '--bare']`.

**If `missing required` is non-empty, stop and report it.** The spec's mapping table needs amending before any of `inference.py` is written.

- [ ] **Step 6: Commit**

```bash
git add src/taller/cli_probe.py tests/unit/test_cli_probe.py
git commit -m "feat(cli_probe): verify the claude flag surface and record its version"
```

---

## Chunk 2: Configuration and the registry

### Task 5: `config.py` — `HubConfig`, deep merge, shipped defaults

**Files:**
- Create: `src/taller/config.py`, `tests/unit/test_config.py`

**Spec:** §4.4.1 and §5.1. `load_hub_config()` must succeed on a completely empty hub, because three callers run before any project exists (§3.6 bootstrap mode).

**The merge rules that matter:**
- Dicts merge deeply; later wins.
- **Lists replace** — except `paths.security_sensitive`, which is **append-only** at every level (§4.4). A project able to narrow its own security surface would make the mandatory security gate optional.
- `language` defaults to `None`, not to any language (§4.0, G9).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_config.py`:

```python
from pathlib import Path

import pytest
import yaml

from taller import config, paths
from taller.errors import ConfigError


def test_empty_hub_loads_with_shipped_defaults(tmp_home: Path):
    cfg = config.load_hub_config()
    assert cfg["language"] is None                      # spec 4.0 — never assumed
    assert cfg["billing"]["mode"] == "subscription"      # no key set, no key present
    assert cfg["model_aliases"]["worker"] == "sonnet"
    assert cfg["models"]["chief"] == "worker"
    assert cfg["effort"]["default"] == "low"
    assert cfg["weights"]["cache_read"] == 0.1
    assert cfg["cli_min_version"] == "2.1.74"


def test_hub_file_overrides_defaults(tmp_home: Path):
    paths.hub().mkdir(parents=True)
    paths.hub_config().write_text(
        yaml.safe_dump({"thresholds": {"max_file_lines": 400}}), encoding="utf-8"
    )
    cfg = config.load_hub_config()
    assert cfg["thresholds"]["max_file_lines"] == 400
    # Unnamed keys keep their default rather than disappearing.
    assert cfg["thresholds"]["max_function_lines"] == 80


def test_deep_merge_dicts_later_wins():
    base = {"a": {"x": 1, "y": 2}}
    over = {"a": {"y": 99}}
    assert config.deep_merge(base, over) == {"a": {"x": 1, "y": 99}}


def test_lists_replace_by_default():
    base = {"paths": {"ui": ["templates/**"]}}
    over = {"paths": {"ui": ["*.html"]}}
    assert config.deep_merge(base, over)["paths"]["ui"] == ["*.html"]


def test_security_sensitive_is_append_only():
    base = {"paths": {"security_sensitive": [".env*"]}}
    over = {"paths": {"security_sensitive": ["routes/**"]}}
    merged = config.deep_merge(base, over)
    assert merged["paths"]["security_sensitive"] == [".env*", "routes/**"]


def test_security_sensitive_cannot_be_narrowed():
    # A project that could drop a hub glob would make the mandatory security
    # gate optional (spec 4.4).
    base = {"paths": {"security_sensitive": [".env*", "database.py"]}}
    over = {"paths": {"security_sensitive": [".env*"]}}
    merged = config.deep_merge(base, over)
    assert "database.py" in merged["paths"]["security_sensitive"]


def test_security_sensitive_does_not_duplicate():
    base = {"paths": {"security_sensitive": [".env*"]}}
    over = {"paths": {"security_sensitive": [".env*", "x/**"]}}
    assert config.deep_merge(base, over)["paths"]["security_sensitive"] == [".env*", "x/**"]


def test_hub_sha_is_empty_when_the_hub_is_not_a_repo(tmp_home: Path):
    cfg = config.load_hub_config()
    assert cfg["hub_sha"] == ""      # the state a first-ever install is in


def test_security_sensitive_rejects_a_scalar(tmp_home: Path):
    # A string here would silently replace the floor (spec 4.4).
    with pytest.raises(ConfigError, match="append-only"):
        config.deep_merge(
            {"paths": {"security_sensitive": [".env*"]}},
            {"paths": {"security_sensitive": "billing/**"}},
        )


def test_resolve_model_maps_role_through_alias(tmp_home: Path):
    cfg = config.load_hub_config()
    assert config.resolve_model("chief", cfg) == "sonnet"
    assert config.resolve_model("architect", cfg) == "opus"
    assert config.resolve_model("scribe", cfg) == "haiku"


def test_resolve_effort_falls_back_to_default(tmp_home: Path):
    cfg = config.load_hub_config()
    assert config.resolve_effort("architect", cfg) == "high"
    assert config.resolve_effort("explorer", cfg) == "low"      # via "default"
    assert config.resolve_effort("nonexistent", cfg) == "low"   # never a KeyError


def test_malformed_yaml_is_a_clear_error(tmp_home: Path):
    paths.hub().mkdir(parents=True)
    paths.hub_config().write_text("this: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="taller.yml"):
        config.load_hub_config()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_config.py -q`
Expected: FAIL — no module named `taller.config`

- [ ] **Step 3: Implement `config.py`**

```python
"""Configuration: the shipped defaults, the deep merge, and the hub-only view.

Spec 4.4 resolves configuration in one chain — hub taller.yml, then profile, then
project taller.yml — separately from slice text. This module owns that chain's
mechanics; constitution.py owns applying it to a project.

Nothing here knows about any particular owner: `language` is None until asked,
and no brand or profile is assumed (spec 4.0, goal G9).
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

from . import paths
from .errors import ConfigError

HubConfig = dict[str, Any]

# Lists normally replace on merge. This one appends, at every level.
APPEND_ONLY_LIST_PATHS = {("paths", "security_sensitive")}

SHIPPED_DEFAULTS: HubConfig = {
    "cli_min_version": "2.1.74",
    "model_aliases": {
        "thinker": "opus",
        "worker": "sonnet",
        "cheap": "haiku",
        "creative": "fable",
    },
    "models": {
        "chief": "worker",
        "architect": "thinker",
        "implementer": "worker",
        "fixer": "worker",
        "gate_security": "thinker",
        "gate_quality": "worker",
        "gate_ux": "worker",
        "explorer": "cheap",
        "scribe": "cheap",
        "summariser": "cheap",
    },
    "effort": {
        "chief": "low",
        "architect": "high",
        "implementer": "medium",
        "fixer": "medium",
        "gate_security": "medium",
        "gate_quality": "medium",
        "gate_ux": "medium",
        "default": "low",
    },
    "fallback": "worker",
    "language": None,          # asked at `taller setup`; never assumed
    "billing": {"mode": None}, # detected; see billing.detect()
    "concurrency": {"max_parallel_gates": 3, "max_parallel_thinker": 1},
    "weights": {"input": 1.0, "cache_write": 1.25, "cache_read": 0.1, "output": 5.0},
    "pricing": {
        "as_of": "2026-06-24",
        "claude-opus-5": {"input": 5.00, "output": 25.00},
        "claude-sonnet-5": {"input": 2.00, "output": 10.00},
        "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
        "claude-fable-5-1": {"input": 10.00, "output": 50.00},
    },
    "budget": {"per_ticket_warn": 400_000, "per_ticket_stop": 1_200_000},
    "thresholds": {
        "max_file_lines": 800,
        "max_function_lines": 80,
        "max_fast_lane_lines": 50,
        "max_fix_rounds": 2,
        "min_coverage_pct": 0,
        "dup_block_lines": 12,
    },
    "paths": {"security_sensitive": [".env*", "**/*secret*", "**/*credential*"]},
}


def deep_merge(base: Any, over: Any, _trail: tuple[str, ...] = ()) -> Any:
    """Merge `over` onto `base`. Later wins; lists replace; one list appends."""
    if isinstance(base, dict) and isinstance(over, dict):
        out = copy.deepcopy(base)
        for key, value in over.items():
            out[key] = deep_merge(out.get(key), value, _trail + (key,))
        return out
    if _trail in APPEND_ONLY_LIST_PATHS:
        # Type-guarded: a scalar here would otherwise silently replace the hub
        # floor, which is exactly what the append-only rule forbids (spec 4.4).
        if not isinstance(over, list):
            raise ConfigError(
                f"{'.'.join(_trail)} must be a list; got {type(over).__name__}. "
                f"It is append-only, so a scalar cannot replace it."
            )
        merged = list(base or [])
        merged.extend(item for item in over if item not in merged)
        return merged
    return copy.deepcopy(over)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping, not {type(data).__name__}.")
    return data


def load_hub_config() -> HubConfig:
    """The hub layer alone. Succeeds on a completely empty hub (spec 4.4.1)."""
    cfg = deep_merge(SHIPPED_DEFAULTS, _read_yaml(paths.hub_config()))
    if cfg["billing"]["mode"] is None:
        cfg["billing"]["mode"] = detect_billing_mode()
    cfg["hub_sha"] = hub_sha()
    return cfg


def hub_sha() -> str:
    """The hub's HEAD, recorded on every gate verdict (spec 4.4.1, 7.4).

    Empty string when the hub is not yet a git repository, which is the state a
    first-ever install is in.
    """
    import subprocess

    if not (paths.hub() / ".git").exists():
        return ""
    try:
        out = subprocess.run(
            ["git", "-C", str(paths.hub()), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
    except OSError:
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def detect_billing_mode() -> str:
    """Determined from the environment, not asked (spec 5.2)."""
    if os.environ.get("CLAUDE_CODE_USE_BEDROCK"):
        return "bedrock"
    if os.environ.get("CLAUDE_CODE_USE_VERTEX"):
        return "vertex"
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "api"
    return "subscription"


def resolve_model(role: str, cfg: HubConfig) -> str:
    """role -> alias -> concrete model id.

    Two hops on purpose: `model_aliases` is the only place a concrete model name
    appears, so a new model release is one line (spec 5.1).
    """
    try:
        alias = cfg["models"][role]
    except KeyError as exc:
        raise ConfigError(f"No model configured for role {role!r}.") from exc
    try:
        return cfg["model_aliases"][alias]
    except KeyError as exc:
        raise ConfigError(
            f"Role {role!r} maps to alias {alias!r}, which no model_aliases entry defines."
        ) from exc


def resolve_effort(role: str, cfg: HubConfig) -> str:
    """The role's key if present, else `default`. Never a KeyError (spec 4.4.1)."""
    effort = cfg["effort"]
    return effort.get(role, effort["default"])
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/unit/test_config.py -q`
Expected: `12 passed`

- [ ] **Step 5: Commit**

```bash
git add src/taller/config.py tests/unit/test_config.py
git commit -m "feat(config): HubConfig, append-only security paths, role->alias->model"
```

---

### Task 6: `registry.py` — the project registry, locked

**Files:**
- Create: `src/taller/registry.py`, `tests/unit/test_registry.py`

**Spec:** §10.2, §10.3. Writes take `registry_lock()`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_registry.py`:

```python
from pathlib import Path

import pytest

from taller import registry
from taller.errors import ConfigError


def test_empty_hub_has_no_projects(tmp_home: Path):
    assert registry.list_projects() == []


def test_add_and_get(tmp_home: Path, tmp_path: Path):
    project = tmp_path / "demo"
    project.mkdir()
    registry.add_project(path=project, name="demo", profile="flask-sqlite", brand="acme")
    assert [p["name"] for p in registry.list_projects()] == ["demo"]
    entry = registry.get_project(project)
    assert entry["profile"] == "flask-sqlite"
    assert entry["brand"] == "acme"
    assert entry["path"] == str(project.resolve())


def test_add_is_idempotent_on_path(tmp_home: Path, tmp_path: Path):
    project = tmp_path / "demo"
    project.mkdir()
    registry.add_project(path=project, name="demo", profile="flask-sqlite", brand=None)
    registry.add_project(path=project, name="demo", profile="static-site", brand=None)
    projects = registry.list_projects()
    assert len(projects) == 1
    assert projects[0]["profile"] == "static-site"   # updated, not duplicated


def test_get_unknown_project_raises(tmp_home: Path, tmp_path: Path):
    with pytest.raises(ConfigError, match="not registered"):
        registry.get_project(tmp_path / "nope")


def test_missing_paths_are_reported_not_hidden(tmp_home: Path, tmp_path: Path):
    project = tmp_path / "gone"
    project.mkdir()
    registry.add_project(path=project, name="gone", profile="flask-sqlite", brand=None)
    project.rmdir()
    assert registry.missing_paths() == [str(project.resolve())]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_registry.py -q`
Expected: FAIL — no module named `taller.registry`

- [ ] **Step 3: Implement `registry.py`**

```python
"""~/.taller/projects.json — which projects Taller knows about.

Writes are serialised on registry_lock() and land through an atomic replace, so a
crash cannot leave a half-written registry (spec 10.3).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import locking, paths
from .errors import ConfigError

Project = dict[str, Any]


def _read() -> list[Project]:
    try:
        text = paths.registry().read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{paths.registry()} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ConfigError(f"{paths.registry()} must contain a list of projects.")
    return data


def list_projects() -> list[Project]:
    return _read()


def get_project(path: Path | str) -> Project:
    wanted = str(Path(path).resolve())
    for project in _read():
        if project["path"] == wanted:
            return project
    raise ConfigError(
        f"{wanted} is not registered. Run `taller project adopt` in it first."
    )


def add_project(*, path: Path | str, name: str, profile: str, brand: str | None) -> Project:
    """Add or update by resolved path. Idempotent, so re-adopting is safe."""
    resolved = str(Path(path).resolve())
    entry: Project = {
        "path": resolved,
        "name": name,
        "profile": profile,
        "brand": brand,
        "last_seen": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with locking.registry_lock():
        projects = [p for p in _read() if p["path"] != resolved]
        projects.append(entry)
        projects.sort(key=lambda p: p["name"])
        locking.atomic_write_text(
            paths.registry(), json.dumps(projects, indent=2) + "\n"
        )
    return entry


def remove_project(path: Path | str) -> None:
    resolved = str(Path(path).resolve())
    with locking.registry_lock():
        projects = [p for p in _read() if p["path"] != resolved]
        locking.atomic_write_text(
            paths.registry(), json.dumps(projects, indent=2) + "\n"
        )


def missing_paths() -> list[str]:
    """Registered paths that no longer exist. `taller doctor` fails on these."""
    return [p["path"] for p in _read() if not Path(p["path"]).is_dir()]
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/unit/test_registry.py -q`
Expected: `5 passed`

- [ ] **Step 5: Run the whole suite and commit**

```bash
python -m pytest -q
git add src/taller/registry.py tests/unit/test_registry.py
git commit -m "feat(registry): locked, atomic project registry"
```

---

## Chunk 3: The inference boundary

### Task 7: The stub `claude`, and `Dispatch`/`Result`

**Files:**
- Create: `tests/stub_claude.py`, `src/taller/inference.py`, `tests/unit/test_inference.py`
- Modify: `tests/conftest.py`

**Spec:** §3.6, §3.6.1, §3.6.2.

**Why a stub:** every inference test must run against a fake binary on `PATH`. A suite that spends the owner's subscription window is a suite nobody runs — and on a subscription the window is the binding limit (§5.2).

- [ ] **Step 1: Write the stub**

`tests/stub_claude.py`:

```python
#!/usr/bin/env python
"""A fake `claude` for tests.

Records the argv it was given to $STUB_CLAUDE_ARGV and answers from
$STUB_CLAUDE_RESPONSE, so a test can assert on the generated argument list —
which spec 15.1 requires, because the argument list *is* the mechanism spec
9.7's guarantee rests on.
"""

import json
import os
import sys


def main() -> int:
    argv_path = os.environ.get("STUB_CLAUDE_ARGV")
    if argv_path:
        with open(argv_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(sys.argv[1:]) + "\n")

    if os.environ.get("STUB_CLAUDE_FAIL_EXIT"):
        sys.stderr.write("stub failure\n")
        return int(os.environ["STUB_CLAUDE_FAIL_EXIT"])

    if os.environ.get("STUB_CLAUDE_BAD_JSON"):
        sys.stdout.write("this is not json")
        return 0

    payload = os.environ.get("STUB_CLAUDE_RESPONSE")
    if payload:
        sys.stdout.write(payload)
        return 0

    sys.stdout.write(json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "session_id": "11111111-2222-3333-4444-555555555555",
        "result": "ok",
        "total_cost_usd": 0.01,
        "usage": {
            "input_tokens": 10,
            "cache_creation_input_tokens": 20,
            "cache_read_input_tokens": 30,
            "output_tokens": 40,
        },
        "modelUsage": {
            "claude-sonnet-5": {
                "inputTokens": 10,
                "cacheCreationInputTokens": 20,
                "cacheReadInputTokens": 30,
                "outputTokens": 40,
            }
        },
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Add the fixture that puts it on `PATH`**

Append to `tests/conftest.py`:

```python
import json
import shutil
import stat
import sys


@pytest.fixture
def stub_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Put a fake `claude` first on PATH and expose what it was called with."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    source = Path(__file__).parent / "stub_claude.py"

    if sys.platform == "win32":
        # A .cmd shim, because Windows will not execute a bare .py from PATH.
        shim = bindir / "claude.cmd"
        # newline="" so text mode does not turn \n into \r\r\n.
        shim.write_text(f'@echo off\n"{sys.executable}" "{source}" %*\n',
                        encoding="utf-8", newline="")
    else:
        shim = bindir / "claude"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{source}" "$@"\n', encoding="utf-8")
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)

    argv_log = tmp_path / "argv.jsonl"
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("STUB_CLAUDE_ARGV", str(argv_log))

    class Stub:
        log = argv_log

        def calls(self) -> list[list[str]]:
            if not argv_log.exists():
                return []
            return [json.loads(line) for line in argv_log.read_text(encoding="utf-8").splitlines()]

        def last(self) -> list[str]:
            return self.calls()[-1]

        def flags(self) -> str:
            return " ".join(self.last())

    return Stub()
```

- [ ] **Step 3: Write the failing tests**

`tests/unit/test_inference.py`:

```python
from pathlib import Path

import pytest

from taller import config, inference, paths
from taller.errors import InferenceError


def _bootstrap_dispatch(**over):
    """A dispatch with no project — the first thing Phase A exercises (spec 3.6)."""
    role = over.get("role", "scribe")
    base = dict(
        role=role,
        prompt="hello",
        ruleset=None,
        config=config.load_hub_config(),
        cwd=None,                                   # -> scratch
        writable=[],
        tools=inference.role_tools(role),           # the spec 3.6.1 table
        forbidden=inference.role_forbidden(role),
        agents=None,
        schema=None,
        unattended=True,
        supports_permission_prompts=False,          # injected, never probed
    )
    base.update(over)
    return inference.Dispatch(**base)


def test_bootstrap_dispatch_needs_no_ruleset(tmp_home, stub_claude):
    result = inference.infer(_bootstrap_dispatch())
    assert result.ok
    assert result.session_id == "11111111-2222-3333-4444-555555555555"


def test_bootstrap_uses_the_scratch_cwd_which_has_no_briefing(tmp_home, stub_claude):
    inference.infer(_bootstrap_dispatch())
    scratch = paths.scratch_cwd()
    assert scratch.is_dir()
    # Spec 3.6: no CLAUDE.md and no .claude/, so a bootstrap dispatch cannot
    # inherit an arbitrary repository's briefing or hooks.
    assert not (scratch / "CLAUDE.md").exists()
    assert not (scratch / ".claude").exists()


def test_model_comes_from_the_role_via_the_alias(tmp_home, stub_claude):
    inference.infer(_bootstrap_dispatch(role="architect"))
    assert "--model opus" in stub_claude.flags()


def test_explicit_model_wins(tmp_home, stub_claude):
    inference.infer(_bootstrap_dispatch(model="haiku"))
    assert "--model haiku" in stub_claude.flags()


def test_bare_is_never_passed(tmp_home, stub_claude):
    # Spec 3.6.2: bare mode never reads OAuth credentials, so it would silently
    # break subscription billing.
    inference.infer(_bootstrap_dispatch())
    assert "--bare" not in stub_claude.last()


def test_session_is_captured_and_replayed(tmp_home, stub_claude):
    first = inference.infer(_bootstrap_dispatch())
    inference.infer(_bootstrap_dispatch(resume=first.session_id))
    assert "--resume" in stub_claude.last()
    assert first.session_id in stub_claude.last()
    # Never pre-generated (spec 3.6).
    assert "--session-id" not in stub_claude.last()


def test_forbidden_expands_to_tool_specifiers_not_paths(tmp_home, stub_claude):
    inference.infer(_bootstrap_dispatch(
        role="fixer", forbidden=["tests/**"], tools=["Read", "Write", "Edit"]
    ))
    flags = stub_claude.flags()
    # Spec 3.6.1: a bare path would match no tool and restrict nothing.
    assert "Write(tests/**)" in flags
    assert "Edit(tests/**)" in flags
    assert "NotebookEdit(tests/**)" in flags
    assert "--disallowedTools tests/**" not in flags


def test_the_role_table_never_gives_the_fixer_bare_bash(tmp_home):
    # The table is the source of truth, so assert on the table itself.
    assert "Bash" not in inference.role_tools("fixer")
    assert inference.role_forbidden("fixer")            # it does restrict paths
    assert any(t.startswith("Bash(") for t in inference.role_tools("fixer"))


def test_the_implementer_keeps_bare_bash_and_forbids_nothing(tmp_home):
    # It must run arbitrary commands to check its own work; --add-dir bounds it.
    assert "Bash" in inference.role_tools("implementer")
    assert inference.role_forbidden("implementer") == []


def test_read_only_roles_get_no_write_tools_and_no_forbidden_list(tmp_home):
    for role in ("explorer", "scribe", "summariser", "gate_security", "gate_ux"):
        tools = inference.role_tools(role)
        assert not {"Write", "Edit", "NotebookEdit"} & set(tools), role
        assert inference.role_forbidden(role) == [], role


def test_a_role_with_forbidden_paths_and_bare_bash_is_a_contract_violation(tmp_home, stub_claude):
    # A shell walks straight around a --disallowedTools specifier (spec 3.6.1).
    # This is a bug in the caller, so it RAISES rather than returning a Result.
    with pytest.raises(InferenceError, match="bare Bash"):
        inference.infer(_bootstrap_dispatch(
            role="fixer", forbidden=["tests/**"], tools=["Read", "Write", "Bash"]
        ))


def test_writing_the_main_worktree_is_a_contract_violation(tmp_home, stub_claude):
    # spec 15.1 requires this be asserted; gitio.commit_to_main() is the only
    # writer of the main-side files.
    forbidden_dir = paths.main_worktree("demo")
    forbidden_dir.mkdir(parents=True)
    with pytest.raises(InferenceError, match="main-worktree"):
        inference.infer(_bootstrap_dispatch(
            role="implementer", writable=[str(forbidden_dir)]
        ))


def test_a_project_directory_merely_named_foo_main_is_allowed(tmp_home, stub_claude, tmp_path):
    # A name-suffix check would have rejected a legitimate checkout.
    legit = tmp_path / "foo-main"
    legit.mkdir()
    result = inference.infer(_bootstrap_dispatch(
        role="implementer", cwd=legit, writable=[str(legit)]
    ))
    assert result.ok


def test_writable_becomes_add_dir(tmp_home, stub_claude, tmp_path):
    work = tmp_path / "wt"
    work.mkdir()
    inference.infer(_bootstrap_dispatch(role="implementer", cwd=work, writable=[str(work)]))
    assert f"--add-dir {work.resolve()}" in stub_claude.flags()


def test_effort_always_reaches_the_dispatch(tmp_home, stub_claude):
    # Native flag, verified present on claude 2.1.74.
    inference.infer(_bootstrap_dispatch(role="architect"))
    assert "--effort high" in stub_claude.flags()


def test_effort_survives_an_explicit_system_prompt(tmp_home, stub_claude):
    # The bootstrap case: `system` replaces the briefing, never the effort.
    inference.infer(_bootstrap_dispatch(role="architect", system="you are a planner"))
    flags = stub_claude.flags()
    assert "--effort high" in flags
    assert "you are a planner" in flags


def test_a_schema_mismatch_is_its_own_failure(tmp_home, stub_claude, monkeypatch):
    # spec 3.6.3 lists it among the failures that each need a distinct reason.
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", (
        '{"session_id":"s","is_error":false,"result":"prose, not structured",'
        '"usage":{"input_tokens":1,"cache_creation_input_tokens":0,'
        '"cache_read_input_tokens":0,"output_tokens":1}}'
    ))
    result = inference.infer(_bootstrap_dispatch(schema={"type": "object"}))
    assert not result.ok
    assert "structured_output" in result.error


def test_a_failed_turn_still_reports_its_usage(tmp_home, stub_claude, monkeypatch):
    # It was billed, so spend must see it (spec 7.5).
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", (
        '{"session_id":"s","is_error":true,"result":"refused",'
        '"usage":{"input_tokens":5,"cache_creation_input_tokens":0,'
        '"cache_read_input_tokens":0,"output_tokens":7}}'
    ))
    result = inference.infer(_bootstrap_dispatch())
    assert not result.ok
    assert result.usage and result.usage[0].output == 7


def test_a_nested_slot_cannot_exceed_the_cap(tmp_home):
    """One thread taking two slots from a one-slot pool must fail, not succeed."""
    from taller.errors import LockTimeout

    pool = paths.dispatch_slots() / "thinker"
    pool.mkdir(parents=True, exist_ok=True)
    outer = inference._acquire_slot(pool, limit=1)
    try:
        with pytest.raises(LockTimeout):
            inference._acquire_slot(pool, limit=1)
    finally:
        outer.__exit__(None, None, None)
    assert not list(pool.glob("*.lock")), "a slot leaked"


def test_the_body_exception_is_not_swallowed_by_the_slot(tmp_home, stub_claude, monkeypatch):
    """An earlier draft yielded inside a try/except in the acquisition loop, so a
    body failure surfaced as `generator didn't stop after throw()`."""
    import subprocess as sp

    def boom(*args, **kwargs):
        raise OSError("BODY BOOM")

    monkeypatch.setattr(sp, "run", boom)
    with pytest.raises(OSError, match="BODY BOOM"):
        inference.infer(_bootstrap_dispatch())


def test_schema_becomes_json_schema(tmp_home, stub_claude, monkeypatch):
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", (
        '{"session_id":"s","is_error":false,'
        '"structured_output":{"verdict":"pass"},'
        '"usage":{"input_tokens":1,"cache_creation_input_tokens":0,'
        '"cache_read_input_tokens":0,"output_tokens":1}}'
    ))
    result = inference.infer(_bootstrap_dispatch(schema={"type": "object"}))
    assert "--json-schema" in stub_claude.flags()
    assert result.value == {"verdict": "pass"}


def test_unattended_sets_permission_mode(tmp_home, stub_claude):
    inference.infer(_bootstrap_dispatch(unattended=True))
    assert "--permission-mode dontAsk" in stub_claude.flags()


def test_usage_is_normalised_to_the_weight_field_names(tmp_home, stub_claude):
    result = inference.infer(_bootstrap_dispatch())
    record = result.usage[0]
    assert record.model == "claude-sonnet-5"
    assert (record.input, record.cache_write, record.cache_read, record.output) == (10, 20, 30, 40)


def test_non_zero_exit_is_an_error_not_an_empty_success(tmp_home, stub_claude, monkeypatch):
    monkeypatch.setenv("STUB_CLAUDE_FAIL_EXIT", "2")
    result = inference.infer(_bootstrap_dispatch())
    assert not result.ok
    assert "exit 2" in result.error


def test_sigterm_exit_143_is_reported_distinctly(tmp_home, stub_claude, monkeypatch):
    monkeypatch.setenv("STUB_CLAUDE_FAIL_EXIT", "143")
    result = inference.infer(_bootstrap_dispatch())
    assert not result.ok
    assert "interrupted" in result.error.lower()


def test_unparseable_json_is_an_error(tmp_home, stub_claude, monkeypatch):
    monkeypatch.setenv("STUB_CLAUDE_BAD_JSON", "1")
    result = inference.infer(_bootstrap_dispatch())
    assert not result.ok
    assert "json" in result.error.lower()


def test_missing_binary_is_an_error(tmp_home, monkeypatch):
    monkeypatch.setenv("PATH", "")
    result = inference.infer(_bootstrap_dispatch())
    assert not result.ok
    assert "not on PATH" in result.error


def test_infer_never_retries(tmp_home, stub_claude, monkeypatch):
    # Retry policy belongs to the caller (spec 3.6, spec 14).
    monkeypatch.setenv("STUB_CLAUDE_FAIL_EXIT", "1")
    inference.infer(_bootstrap_dispatch())
    assert len(stub_claude.calls()) == 1
```

- [ ] **Step 4: Run to verify they fail**

Run: `python -m pytest tests/unit/test_inference.py -q`
Expected: FAIL — no module named `taller.inference`

- [ ] **Step 5: Implement `inference.py`**

```python
"""The only module that spawns the `claude` CLI.

Everything else asks for a dispatch and receives a result, so how inference is
performed is a single decision in a single place (spec 3.6). That is also the
only reason replacing the subprocess with an embedded Agent SDK client would be
a swap rather than a rewrite — though doing so would forfeit subscription
billing (spec 5.2) and is not expected.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config, paths
from .errors import InferenceError

# Tools that can modify a file. `forbidden` globs expand across all of them,
# because --disallowedTools matches tools, not paths (spec 3.6.1).
WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")

BARE_BASH = "Bash"

READ_ONLY = ["Read", "Glob", "Grep"]

# Spec 3.6.1's per-role table, verbatim. It lives here rather than at each call
# site because spec 15.1 asserts on the generated argument list and cannot be
# written against "the specifiers it needs".
#
# Two properties worth noting:
#   * A read-only role has NO forbidden list. It is granted no write-capable
#     tool, so there is nothing to forbid.
#   * `implementer` keeps bare Bash and has an empty forbidden list; it must be
#     able to run arbitrary commands to check its own work, and is bounded by
#     --add-dir alone. The no-test-file rule is the FIXER's, because "make a
#     failing test pass by editing the test" is a fix round's temptation.
ROLE_TOOLS: dict[str, list[str]] = {
    "chief": READ_ONLY + ["Bash(git status*)", "Bash(git log*)", "Bash(git diff*)"],
    "explorer": READ_ONLY,
    "scribe": ["Read"],
    "summariser": ["Read"],
    "gate_security": READ_ONLY,
    "gate_quality": READ_ONLY,
    "gate_ux": READ_ONLY,
    "architect": READ_ONLY + ["Write", "Edit"],
    "implementer": READ_ONLY + ["Write", "Edit", "NotebookEdit", BARE_BASH],
    "fixer": READ_ONLY + [
        "Write", "Edit", "NotebookEdit",
        "Bash(pytest*)", "Bash(python -m pytest*)",
        "Bash(git diff*)", "Bash(git status*)",
    ],
}

# Only the fixer restricts paths, and only the fixer therefore loses bare Bash.
FIXER_FORBIDDEN = ["**/test_*.py", "**/*_test.py"]


def role_tools(role: str) -> list[str]:
    """The allowlist for a role. Raises rather than silently granting nothing."""
    try:
        return list(ROLE_TOOLS[role])
    except KeyError as exc:
        raise InferenceError(f"No tool allowlist defined for role {role!r}.") from exc


def role_forbidden(role: str, tests_dir: str = "tests") -> list[str]:
    """The forbidden globs for a role. Empty for every role but the fixer."""
    if role != "fixer":
        return []
    return [f"{tests_dir}/**", *FIXER_FORBIDDEN]


@dataclass
class UsageRecord:
    """Named for the four fields `weights` and `pricing` are keyed by (spec 5.1),
    so the rename from the CLI's field names happens once, here."""
    model: str
    input: int = 0
    cache_write: int = 0
    cache_read: int = 0
    output: int = 0


@dataclass
class Dispatch:
    role: str
    prompt: str
    config: config.HubConfig
    ruleset: dict[str, Any] | None = None
    model: str | None = None
    effort: str | None = None
    system: str | None = None
    resume: str | None = None
    cwd: Path | str | None = None       # None -> the bootstrap scratch dir
    writable: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    agents: dict[str, Any] | None = None
    schema: dict[str, Any] | None = None
    unattended: bool = True
    # Injected by the caller from cli_probe, never probed here: probing inside
    # infer() spawned `claude --help` on the first dispatch of every process,
    # which made a "never retries" assertion order-dependent.
    supports_permission_prompts: bool = False


@dataclass
class Result:
    ok: bool
    value: Any = None
    error: str | None = None
    session_id: str = ""
    usage: list[UsageRecord] = field(default_factory=list)
    cost_usd: float | None = None       # CUMULATIVE when resuming (spec 7.5)


def infer(dispatch: Dispatch, executable: str = "claude") -> Result:
    """Perform one act of inference. Never retries — that is the caller's policy.

    Two classes of failure, deliberately different:
      * A *contract violation* by an internal caller — a role holding both bare
        Bash and forbidden paths, or a dispatch trying to write the main worktree
        — RAISES InferenceError. These are bugs in Taller, not runtime conditions,
        and folding them into a Result would hide the guarantee spec 9.7 rests on.
      * A *runtime* failure — bad exit, bad JSON, schema mismatch, missing binary
        — returns ok: false with a distinct reason, for the caller's retry policy.
    """
    argv_tail, cwd = _build(dispatch, executable)   # may raise: see above

    # Resolve to an absolute path BEFORE spawning. On Windows, CreateProcess
    # appends only .exe to an extensionless name, so spawning bare "claude" skips
    # a claude.cmd earlier on PATH and runs the real claude.exe instead — which
    # would make the whole test suite issue real, billed dispatches.
    resolved = shutil.which(executable)
    if resolved is None:
        return Result(
            ok=False,
            error=f"The `{executable}` CLI is not on PATH. Taller performs every "
                  f"act of inference through it.",
        )
    argv = [resolved, *argv_tail]

    with _slot(dispatch):
        completed = subprocess.run(
            argv, input=dispatch.prompt, capture_output=True, text=True, cwd=str(cwd)
        )

    if completed.returncode == 143:
        return Result(
            ok=False,
            error="The dispatch was interrupted (exit 143); the turn is unfinished "
                  "and no result was recorded.",
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[:500]
        return Result(ok=False, error=f"`{executable}` failed with exit "
                                      f"{completed.returncode}: {detail}")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return Result(ok=False, error=f"`{executable}` returned output that is not "
                                      f"JSON: {exc}")

    if payload.get("is_error"):
        # A failed turn was still billed, so its usage must be recorded (spec 7.5).
        return Result(ok=False, error=str(payload.get("result", "unknown error")),
                      session_id=payload.get("session_id", ""),
                      usage=_usage(payload),
                      cost_usd=payload.get("total_cost_usd"))

    if dispatch.schema is not None and "structured_output" not in payload:
        return Result(
            ok=False,
            error="A schema was requested but the answer carried no "
                  "`structured_output`; the model did not satisfy it.",
            session_id=payload.get("session_id", ""),
            usage=_usage(payload),
            cost_usd=payload.get("total_cost_usd"),
        )

    value = payload.get("structured_output", payload.get("result"))
    return Result(
        ok=True,
        value=value,
        session_id=payload.get("session_id", ""),
        usage=_usage(payload),
        cost_usd=payload.get("total_cost_usd"),
    )


def _build(dispatch: Dispatch, executable: str) -> tuple[list[str], Path]:
    cfg = dispatch.ruleset or dispatch.config

    model = dispatch.model or config.resolve_model(dispatch.role, cfg)
    effort = dispatch.effort or config.resolve_effort(dispatch.role, cfg)

    # Spec 3.6.1: a shell circumvents a --disallowedTools specifier, so a role
    # with forbidden paths may not hold bare Bash.
    if dispatch.forbidden and BARE_BASH in dispatch.tools:
        raise InferenceError(
            f"Role {dispatch.role!r} has forbidden paths but its allowlist contains "
            f"bare Bash. A shell circumvents --disallowedTools specifiers, so this "
            f"combination would make the restriction cosmetic. Allowlist the "
            f"specific Bash(...) specifiers it needs instead."
        )

    cwd = Path(dispatch.cwd) if dispatch.cwd else paths.scratch_cwd()
    cwd.mkdir(parents=True, exist_ok=True)

    # argv WITHOUT the executable; infer() prepends the resolved absolute path.
    argv = ["-p", "--output-format", "json", "--model", model, "--effort", effort]

    # `system` replaces the slice briefing, never the effort. An earlier draft
    # computed effort and then discarded it whenever a caller supplied `system`,
    # which is exactly the bootstrap case.
    system = dispatch.system or _brief(dispatch)
    if system:
        argv += ["--append-system-prompt", system]
    if dispatch.resume:
        argv += ["--resume", dispatch.resume]
    if dispatch.tools:
        argv += ["--allowedTools", ",".join(dispatch.tools)]
    if dispatch.forbidden:
        argv += ["--disallowedTools", ",".join(_expand_forbidden(dispatch.forbidden))]
    worktrees_root = (paths.run_dir() / "worktrees").resolve()
    for directory in dispatch.writable:
        candidate = Path(directory).resolve()
        # Compare against the real location, not a name suffix: a legitimate
        # checkout called `foo-main` must not be rejected.
        if candidate == worktrees_root or worktrees_root in candidate.parents:
            raise InferenceError(
                f"{candidate} is inside the main-worktree root and must never be "
                f"writable by a dispatch; gitio.commit_to_main() is its only "
                f"writer (spec 3.6.1)."
            )
        argv += ["--add-dir", str(candidate)]
    if dispatch.schema is not None:
        argv += ["--json-schema", json.dumps(dispatch.schema)]
    if dispatch.agents is not None:
        argv += ["--agents", json.dumps(dispatch.agents)]
    if dispatch.unattended:
        argv += ["--permission-mode", "dontAsk"]
        if dispatch.supports_permission_prompts:
            argv += ["--permission-prompts", "none"]

    # --bare is deliberately absent: it never reads OAuth credentials, so it
    # would silently require an API key (spec 3.6.2).
    return argv, cwd


def _brief(dispatch: Dispatch) -> str:
    """The role's slices, concatenated. Effort travels as --effort, not as prose."""
    slices = (dispatch.ruleset or {}).get("slices") or {}
    parts = [
        resolved["text"] if isinstance(resolved, dict) else str(resolved)
        for resolved in slices.values()
    ]
    return "\n\n".join(p for p in parts if p)


def _expand_forbidden(globs: list[str]) -> list[str]:
    return [f"{tool}({glob})" for glob in globs for tool in WRITE_TOOLS]


def _usage(payload: dict[str, Any]) -> list[UsageRecord]:
    per_model = payload.get("modelUsage") or {}
    if per_model:
        return [
            UsageRecord(
                model=model,
                input=int(u.get("inputTokens", 0)),
                cache_write=int(u.get("cacheCreationInputTokens", 0)),
                cache_read=int(u.get("cacheReadInputTokens", 0)),
                output=int(u.get("outputTokens", 0)),
            )
            for model, u in per_model.items()
        ]
    usage = payload.get("usage") or {}
    if not usage:
        return []
    return [UsageRecord(
        model=payload.get("model", "unknown"),
        input=int(usage.get("input_tokens", 0)),
        cache_write=int(usage.get("cache_creation_input_tokens", 0)),
        cache_read=int(usage.get("cache_read_input_tokens", 0)),
        output=int(usage.get("output_tokens", 0)),
    )]


@contextlib.contextmanager
def _slot(dispatch: Dispatch):
    """A counted semaphore across processes.

    The limit being protected is a per-account usage window (spec 5.2), and the
    CLI, the cockpit and a Claude Code session can all dispatch at once — so a
    per-process counter would bound nothing that matters.

    The slot is acquired BEFORE the yield and released in a finally. An earlier
    draft yielded inside a `try/except Exception` inside the acquisition loop,
    which caught the wrapped body's own exception, retried the loop, and surfaced
    as `RuntimeError: generator didn't stop after throw()` with the real cause
    gone — while abandoning the generator still holding the lock.
    """
    from . import locking

    cfg = dispatch.ruleset or dispatch.config
    concurrency = cfg.get("concurrency", {})
    thinker = cfg.get("model_aliases", {}).get("thinker")
    model = dispatch.model or config.resolve_model(dispatch.role, cfg)

    # Two pools, matching spec 5.1's two keys. One shared namespace would make an
    # Opus dispatch queue behind an unrelated Sonnet one, and would apply the gate
    # limit to the chief, the implementer and the scribe as well.
    if model == thinker:
        pool, limit = "thinker", concurrency.get("max_parallel_thinker", 1)
    else:
        pool, limit = "worker", concurrency.get("max_parallel_gates", 3)
    limit = max(1, int(limit))

    pool_dir = paths.dispatch_slots() / pool
    pool_dir.mkdir(parents=True, exist_ok=True)

    acquired = _acquire_slot(pool_dir, limit)
    try:
        yield                       # exactly one yield, outside any except
    finally:
        acquired.__exit__(None, None, None)


def _acquire_slot(pool_dir: Path, limit: int):
    """Take the first free slot, or wait on slot 0 when all are busy.

    Returns the entered context manager so the caller can release it in a
    `finally`. Only slot acquisition is guarded here; the body is not.
    """
    from . import locking
    from .errors import LockTimeout

    for index in range(limit):
        candidate = locking.file_lock(
            pool_dir / f"slot-{index}.lock", timeout=0.05, reentrant=False
        )
        try:
            candidate.__enter__()
        except LockTimeout:
            continue                # that slot is busy; try the next
        return candidate

    waiting = locking.file_lock(pool_dir / "slot-0.lock", timeout=300, reentrant=False)
    waiting.__enter__()
    return waiting
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/unit/test_inference.py -q`
Expected: `28 passed`

Then confirm the stub really ran, which is the whole point of Task 7:

```bash
python -m pytest tests/unit/test_inference.py -q && echo "OK: no real dispatches"
```

If any test reports a `session_id` other than `11111111-2222-3333-4444-555555555555`, the real binary was invoked — stop and check that `infer` is spawning the resolved absolute path.

- [ ] **Step 7: Commit**

```bash
git add src/taller/inference.py tests/stub_claude.py tests/conftest.py tests/unit/test_inference.py
git commit -m "feat(inference): the sole caller of claude, with bootstrap mode and harness-enforced paths"
```

---

### Task 8: Cross-process concurrency, proved

**Files:**
- Modify: `tests/unit/test_inference.py`

**Why a separate task:** §15.1 requires the cap to hold "across two processes, not just within one". That needs a second interpreter, so it is slower and easier to debug on its own.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_inference.py`:

```python
def test_concurrency_cap_holds_across_processes(tmp_home, stub_claude, tmp_path, monkeypatch):
    """A per-process counter would bound nothing (spec 3.6)."""
    import subprocess
    import sys
    import textwrap
    import time

    pool = paths.dispatch_slots() / "thinker"      # two pools, per spec 5.1
    pool.mkdir(parents=True, exist_ok=True)
    ready = tmp_path / "slot-ready"

    # Occupy the single thinker slot from another process.
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import pathlib, time
        from taller import locking
        with locking.file_lock({str(pool / 'slot-0.lock')!r}):
            pathlib.Path({str(ready)!r}).write_text("1")
            time.sleep(6)
    """)])
    try:
        # Wait for the holder to really have it, rather than guessing.
        deadline = time.monotonic() + 20
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "holder never acquired the slot"

        # Time the ACQUISITION, not the whole dispatch: timing infer() would pass
        # with a per-process semaphore whenever a dispatch itself took >= 1.5s.
        started = time.monotonic()
        acquired = inference._acquire_slot(pool, limit=1)
        waited = time.monotonic() - started
        acquired.__exit__(None, None, None)
        assert waited >= 1.5, f"slot acquisition did not block (waited {waited:.1f}s)"
    finally:
        holder.kill()
        holder.wait()
```

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/unit/test_inference.py::test_concurrency_cap_holds_across_processes -q`
Expected: PASS. If it fails with `waited 0.0s`, the semaphore is per-process and the fix belongs in `_slot`.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_inference.py
git commit -m "test(inference): prove the concurrency cap holds across processes"
```

---

## Review checkpoint

Chunks 1–3 give a package that can talk to `claude` safely, with configuration and locking underneath. Before continuing:

- [ ] Run the whole suite: `python -m pytest -q` — expect everything green.
- [ ] Confirm no test invoked the real binary: `grep -rn "Popen" tests/` should show exactly the two deliberate second-process tests (`test_locking.py`, `test_inference.py`) and nothing else.
- [ ] Dispatch the plan reviewer on chunks 1–3 with the spec path, and fix what it finds before Chunk 4.

---

## Chunk 4: The catalogue, and the code that installs it

The catalogue is where the tool's genericity stops being a claim and becomes files. Everything in it is named for a stack, never for a line of business, and nothing in it is active until copied into a hub (§4.0).

**A note on how this chunk is specified.** Tasks 9 and 10 produce **data** — prose modules and YAML profiles — whose correctness is defined entirely by machine-checkable invariants. So the plan specifies the *invariants and their tests*, and the content is authored directly against them. Transcribing nine prose files through a plan would add a copying step without adding a check. Task 11 is logic and is specified in full.

### Task 9: The nine module files

**Files:** `src/taller/catalogue/modules/` — `stack/{flask-sqlite,static-site,python-packaged}.md`, `security/{web-app,minimal}.md`, `conventions/{python,js}.md`, `ux/bootstrap.md`, `never.md`
**Test:** `tests/unit/test_catalogue_content.py`

**The invariants**, each a test:

| # | Invariant | Why |
|---|---|---|
| 1 | Exactly nine modules ship | The three profiles between them name all nine |
| 2 | **Every file's first line is a `> ` sentence of ≤ 100 chars** | `render_index` collects these verbatim to build the 40-line index (§3.1). A module without one leaves a hole in it. |
| 3 | No file mentions a domain, brand or person | Goal G9. The catalogue is inside the package, so §15.6's vocabulary rule covers it. |
| 4 | Every file is UTF-8 with LF endings | Generated artefacts are compared byte-for-byte (§4.6) |
| 5 | Each file's parent directory names one of the nine slices | §4.3's closed vocabulary |

- [ ] **Step 1:** Write `tests/unit/test_catalogue_content.py` asserting invariants 1–5. Use `pytest.mark.parametrize` over the discovered files so each module reports separately.
- [ ] **Step 2:** Run it. Expected: FAIL — invariant 1 asserts `0 == 9`, and the parametrised tests collect zero cases, which is itself the signal.
- [ ] **Step 3:** Author the nine modules against the invariants. Content guidance: each is agent-facing prose that answers "what must someone know to work in this stack" — runtime, layout, the two or three rules whose violation causes real damage. Say *why*, not just what. `never.md` additionally carries YAML front matter with an empty `non_suppressible: []` (§4.5).
- [ ] **Step 4:** Run the tests. Expected: `1 + 4×9 = 37 passed`.
- [ ] **Step 5:** Commit — `feat(catalogue): nine generic stack modules, each with an index summary`

### Task 10: The three profiles

**Files:** `src/taller/catalogue/profiles/{flask-sqlite,static-site,python-packaged}.yml`
**Test:** append to `tests/unit/test_catalogue_content.py`

**The invariants:**

| # | Invariant | Why |
|---|---|---|
| 6 | Exactly those three profile names | §4.1 |
| 7 | **`brand: null` and no `language` key** | Both are asked, never assumed (§4.0). A shipped default here is precisely how a tool ends up knowing whose it is. |
| 8 | Every module a profile names exists in the catalogue | A profile copy is atomic with its modules (§4.0); a dangling name would make the first `project new` fail on a fresh hub |
| 9 | `name` matches the filename; `description` non-empty; `paths` carries `security_sensitive`, `ui`, `layers`, `tests_dir`, `brand_tokens`; `smoke.kind` ∈ {`http`,`import`,`none`} | These are the keys `resolve()` and the smoke gate read |

`paths.brand_tokens` differs per profile and must not be hardcoded anywhere: `static/css/tokens.css` for `flask-sqlite`, `tokens.css` for `static-site` (its assets sit at the root), `null` for `python-packaged` (no brand, no generated token file).

- [ ] **Step 1:** Write the tests for invariants 6–9.
- [ ] **Step 2:** Run. Expected: FAIL on invariant 6.
- [ ] **Step 3:** Author the three profiles.
- [ ] **Step 4:** Run. Expected: `47 passed`.
- [ ] **Step 5:** Commit — `feat(catalogue): three stack profiles, none naming a brand or a language`

### Task 11: `catalogue.py` — installing into the hub, atomically

**Files:** Create `src/taller/catalogue.py`, `tests/unit/test_catalogue.py`

**The rule everything else rests on** (§4.0): **copying a profile copies every module it names.** Chain 2 resolves slice text from `~/.taller/modules/`, so a profile whose modules stayed behind resolves dangling references — and that is the single step the entire empty-hub contract depends on. A module already in the hub is **never overwritten**: the catalogue is a starting point, not an upstream you track.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_catalogue.py`

```python
from pathlib import Path

import pytest

from taller import catalogue, paths
from taller.errors import ConfigError


def test_list_profiles_reads_the_catalogue_not_the_hub(tmp_home: Path):
    """An empty hub still offers the catalogue's profiles — which is all a first
    `project new` has to choose from (spec 4.7)."""
    assert not paths.profiles().exists()
    assert set(catalogue.list_profiles()) == {
        "flask-sqlite", "static-site", "python-packaged"
    }


def test_copying_a_profile_brings_its_modules(tmp_home: Path):
    catalogue.install_profile("flask-sqlite")
    assert (paths.profiles() / "flask-sqlite.yml").is_file()
    for module in ("stack/flask-sqlite", "security/web-app", "conventions/python",
                   "conventions/js", "ux/bootstrap", "never"):
        assert (paths.modules() / f"{module}.md").is_file(), module


def test_an_existing_module_is_never_overwritten(tmp_home: Path):
    """The catalogue is a starting point, not an upstream. An edited module is
    the owner's."""
    catalogue.install_profile("flask-sqlite")
    edited = paths.modules() / "conventions" / "python.md"
    edited.write_text("> Mine now.\n\nMy own conventions.\n", encoding="utf-8")
    catalogue.install_profile("flask-sqlite")
    assert edited.read_text(encoding="utf-8").startswith("> Mine now.")


def test_an_existing_profile_is_never_overwritten(tmp_home: Path):
    catalogue.install_profile("static-site")
    target = paths.profiles() / "static-site.yml"
    target.write_text("name: static-site\nmine: true\n", encoding="utf-8")
    catalogue.install_profile("static-site")
    assert "mine: true" in target.read_text(encoding="utf-8")


def test_installing_an_unknown_profile_is_a_clear_error(tmp_home: Path):
    with pytest.raises(ConfigError, match="no-such-profile"):
        catalogue.install_profile("no-such-profile")


def test_installed_files_are_lf(tmp_home: Path):
    """Generated and installed files are compared byte-for-byte later (spec 4.6)."""
    catalogue.install_profile("python-packaged")
    for path in (list(paths.modules().rglob("*.md"))
                 + list(paths.profiles().glob("*.yml"))):
        assert b"\r\n" not in path.read_bytes(), path


def test_install_reports_what_it_did(tmp_home: Path):
    report = catalogue.install_profile("python-packaged")
    assert report.profile == "python-packaged"
    assert len(report.modules_copied) == 4
    assert report.modules_kept == []

    again = catalogue.install_profile("python-packaged")
    assert again.modules_copied == []
    assert len(again.modules_kept) == 4


def test_missing_modules_reports_a_broken_hub_profile(tmp_home: Path):
    """`doctor` fails on these (spec 4.0)."""
    catalogue.install_profile("python-packaged")
    (paths.modules() / "never.md").unlink()
    assert catalogue.missing_modules("python-packaged") == ["never"]
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/unit/test_catalogue.py -q`. Expected: no module named `taller.catalogue`.

- [ ] **Step 3: Implement `src/taller/catalogue.py`**

```python
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
```

- [ ] **Step 4: Run the tests** — Expected: `8 passed`
- [ ] **Step 5: Run the whole suite and commit**

```bash
python -m pytest -q
git add src/taller/catalogue.py tests/unit/test_catalogue.py
git commit -m "feat(catalogue): install a profile atomically with its modules, never overwriting"
```

---

## Chunk 5: Resolution — `overrides.py` and `constitution.py`

The chunk the rest of Phase A waits on. `resolve()` is the contract every later component reads, and the three renderers produce the files the tamper check compares byte-for-byte.

Specified as Tasks 9–10 were: the **contracts, invariants and the decisions that are not obvious**, with the implementation written against them. The tests are the gate.

### Task 12: `overrides.py` (§4.5)

**Files:** `src/taller/overrides.py`, `tests/unit/test_overrides.py`

| # | Invariant | Why it matters |
|---|---|---|
| 1 | A suppressed finding is **downgraded to `NIT` and annotated with its reason** — never removed | An override is a decision to ship a known deviation, not to stop knowing about it. It stays visible in the verdict, on the cockpit and in `taller scan`. |
| 2 | Every rule in the **`security` domain** is non-suppressible, by domain | A security rule added later is protected without anyone remembering to list it |
| 3 | Every id in the resolved **`non_suppressible`** list is non-suppressible | Append-only config (§4.4), so a project can add but never remove |
| 4 | An attempt to suppress either is reported at **`BLOCKER`** and suppresses nothing | |
| 5 | Missing reason and past-`until` get **distinct rule ids** | §15.1 asserts by id; two conditions sharing one id cannot be told apart |
| 6 | A file with no front matter parses to `[]` | A project with no overrides is the normal case, not an error |
| 7 | `scope` defaults to `*`; a `scope` that does not match the finding's file does not suppress | |

Rule ids this module reports: `constitution.override-without-reason` (HIGH), `constitution.override-expired` (HIGH), `constitution.override-not-permitted` (BLOCKER), `constitution.unknown-rule-id` (MEDIUM).

**Known limitation to record, not fix:** `fnmatch` does not implement recursive globbing — `**` behaves as `*`, and `*` matches a path separator. For scope matching that is acceptable and slightly permissive in the safe direction, but worth knowing before someone "corrects" it.

- [ ] Write the tests for invariants 1–7 · run them failing · implement · expect **17 passed** · commit `feat(overrides): downgrade what an override covers, refuse what it may not`

### Task 13: `constitution.resolve()` (§4.3, §4.4, §4.4.1)

**Files:** `src/taller/constitution.py`, `tests/unit/test_constitution.py`, plus `config.read_project_config`

Two chains, deliberately separate:

- **Chain 1 — configuration:** hub `taller.yml` → profile → project `taller.yml`, by deep merge. **Nothing in `constitution/` sets configuration**, and a test writes a `thresholds:` block into a slice file to prove it has no effect.
- **Chain 2 — slice text:** hub modules in profile order → project `constitution/` → project `never.md` **appended**. Prose is only ever appended, so a project cannot delete a hub prohibition; the only way a rule stops applying is an override with a reason.

| # | Invariant |
|---|---|
| 1 | The nine slice names of §4.3 and no others; a slice a project does not provide is **absent**, not empty |
| 2 | `product`, `architecture` and `overrides` are **project-only** — a hub module of that name is ignored, not merged |
| 3 | `conventions` concatenates several modules **in profile order** (`python` before `js` for `flask-sqlite`) |
| 4 | A project `never.md` is appended and the hub's prohibitions survive |
| 5 | Chain 1 merges hub → profile → project, and `paths.security_sensitive` cannot be narrowed |
| 6 | `RuleSet["models"]` holds **aliases**, so `config.resolve_model` serves both it and `HubConfig` |
| 7 | `brand: none` yields `brand: None`; a real brand contributes parsed `--tokens` and its `brand.md` prose |
| 8 | `mode` is `"local"`; `hub_sha` present |
| 9 | **`resolve()` writes nothing** — asserted by comparing every file's mtime before and after. This purity is what makes §4.6's byte-for-byte check possible. |
| 10 | An unregistered project, and a profile naming a module the hub lacks, both raise a clear `ConfigError` |

- [ ] Write the tests · run failing · implement · expect **17 passed** · commit `feat(constitution): resolve two chains into a RuleSet, writing nothing`

### Task 14: The three renderers and `load_snapshot` (§4.6, §3.1, §4.2.1)

**Files:** extend `src/taller/constitution.py`; `tests/unit/test_renderers.py`; extract the project-building helper into `tests/support.py` rather than duplicating it.

All three are `RuleSet → bytes`, all pure, all compared byte-for-byte later — so all must be **byte-stable across two calls**, or the tamper check reports a clean repository as modified.

| # | Invariant |
|---|---|
| 1 | `render_snapshot` is byte-stable across two calls; LF; valid UTF-8 JSON; sorted keys |
| 2 | The snapshot **carries the slice text**, because CI cannot see the hub (§4.6) |
| 3 | A loaded snapshot has `mode == "ci"` |
| 4 | `render_index` is byte-stable, within its **600-token budget**, and **raises rather than silently exceeding it** |
| 5 | The index collects each slice's own first `> ` line verbatim, and carries the routing table with `stack`, `never`, `overrides` in the always row |
| 6 | The index's prose is ≤ 40 lines |
| 7 | `render_tokens` is a verbatim copy of the brand's file behind a generated-file header, and returns `None` when there is no brand |

**On the token budget.** There is no local tokenizer and a real count costs an API call, so `estimate_tokens` uses `ceil(len(text) / 3.5)` — deliberately pessimistic, so passing the check means the true count is almost certainly lower. The docstring says it is an approximation rather than implying precision.

- [ ] Write the tests · run failing · implement · expect **10 passed** · commit `feat(constitution): byte-stable snapshot, index and token renderers`

---

## Chunks 6–8: written after Chunk 5 is green

| Chunk | Contents | Spec |
|---|---|---|
| **6** | `gitio.py` — `ensure_main_worktree()`, `commit_to_main()` with no-remote mode and the three `sync` states | §7.3 |
| **7** | `brands.py` (`from_pdf` first, it is the preferred source), `scaffold.py`, `discovery.py` | §4.2, §4.7, §11.4 |
| **8** | `cli.py`, the command modules, `doctor.py`, and the greenfield acceptance test of §15.5 | §3.5, §15.4, §15.5 |

The acceptance test in chunk 8 is the phase's real exit condition: `project new` against an empty `HOME`, once per catalogue profile, then `doctor` green with nothing skipped that Phase A provides.
