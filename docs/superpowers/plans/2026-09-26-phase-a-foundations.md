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
├── templates/catalogue/
│   ├── modules/                    stack/ security/ conventions/ ux/ never.md
│   ├── profiles/                   flask-sqlite.yml static-site.yml python-packaged.yml
│   └── scaffolds/<profile>/        manifest.yml + *.j2
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

Run the suite with:

```bash
python -m pytest -q
```

---

## Chunk 1: Skeleton, locking, paths

### Task 1: Repository skeleton and a green empty suite

**Files:**
- Create: `pyproject.toml`, `src/taller/__init__.py`, `src/taller/errors.py`, `tests/conftest.py`, `tests/unit/test_smoke.py`

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
python -m pip install -e ".[dev]"
python -m pytest tests/unit/test_smoke.py -q
```

Expected: `1 passed`. Note that this also installs `pypdf`, which is **not currently present** on this machine.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src tests
git commit -m "chore: package skeleton, error hierarchy, empty test suite"
```

---

### Task 2: `paths.py` — one place that knows where things live

**Files:**
- Create: `src/taller/paths.py`, `tests/unit/test_paths.py`
- Modify: `tests/conftest.py`

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


def test_catalogue_ships_with_the_package():
    # The catalogue is inside the installed package, not in the hub (spec 4.0).
    assert paths.catalogue().is_dir()
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
    return Path(__file__).resolve().parent.parent.parent / "templates" / "catalogue"


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

    holder = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
            import time
            from taller import locking
            with locking.file_lock({str(lock)!r}):
                time.sleep(8)
        """)],
    )
    try:
        import time
        time.sleep(1.5)  # let the holder acquire
        with pytest.raises(LockTimeout):
            with locking.file_lock(lock, timeout=5):
                target.write_text("clobbered", encoding="utf-8")
        assert target.read_text(encoding="utf-8") == "original"
    finally:
        holder.kill()
        holder.wait()


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
import time
from collections import defaultdict
from pathlib import Path
from typing import Iterator

from .errors import LockTimeout

DEFAULT_TIMEOUT = 5.0
_POLL = 0.05

# lock path (resolved, as str) -> re-entrancy depth for THIS process
_depth: dict[str, int] = defaultdict(int)


def held(lock_path: Path | str) -> bool:
    """True when this process currently holds the lock."""
    return _depth[str(Path(lock_path).resolve())] > 0


@contextlib.contextmanager
def file_lock(lock_path: Path | str, timeout: float = DEFAULT_TIMEOUT) -> Iterator[None]:
    """Hold an exclusive lock. Re-entrant within this process.

    Raises LockTimeout rather than waiting indefinitely or forcing, so a stuck
    holder produces a clear message instead of a hang.
    """
    path = Path(lock_path).resolve()
    key = str(path)

    if _depth[key] > 0:            # already ours — just count deeper
        _depth[key] += 1
        try:
            yield
        finally:
            _depth[key] -= 1
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
    _depth[key] = 1
    try:
        yield
    finally:
        _depth[key] = 0
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


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
Expected: `5 passed`. The cross-process test takes ~6 seconds; that is the timeout being proved.

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

    if shutil.which(executable) is None:
        raise InferenceError(
            f"The `{executable}` CLI is not on PATH. Taller performs every act of "
            f"inference through it (spec 3.6) and cannot work without it."
        )
    help_text = subprocess.run(
        [executable, "--help"], capture_output=True, text=True, timeout=60
    ).stdout
    version_text = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, timeout=60
    ).stdout
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
    if isinstance(base, list) and isinstance(over, list) and _trail in APPEND_ONLY_LIST_PATHS:
        merged = list(base)
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
    return cfg


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
Expected: `10 passed`

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
    with locking.file_lock(paths.registry_lock()):
        projects = [p for p in _read() if p["path"] != resolved]
        projects.append(entry)
        projects.sort(key=lambda p: p["name"])
        locking.atomic_write_text(
            paths.registry(), json.dumps(projects, indent=2) + "\n"
        )
    return entry


def remove_project(path: Path | str) -> None:
    resolved = str(Path(path).resolve())
    with locking.file_lock(paths.registry_lock()):
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
        shim.write_text(f'@echo off\r\n"{sys.executable}" "{source}" %*\r\n', encoding="utf-8")
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
    base = dict(
        role="scribe",
        prompt="hello",
        ruleset=None,
        config=config.load_hub_config(),
        cwd=None,            # -> scratch
        writable=[],
        forbidden=[],
        tools=["Read"],
        agents=None,
        schema=None,
        unattended=True,
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


def test_a_role_with_forbidden_paths_never_gets_bare_bash(tmp_home, stub_claude):
    # A shell walks straight around a --disallowedTools specifier (spec 3.6.1).
    with pytest.raises(InferenceError, match="bare Bash"):
        inference.infer(_bootstrap_dispatch(
            role="fixer", forbidden=["tests/**"], tools=["Read", "Write", "Bash"]
        ))


def test_writable_becomes_add_dir_and_main_worktree_is_never_included(tmp_home, stub_claude, tmp_path):
    work = tmp_path / "wt"
    work.mkdir()
    inference.infer(_bootstrap_dispatch(role="implementer", cwd=work, writable=[str(work)]))
    flags = stub_claude.flags()
    assert f"--add-dir {work}" in flags
    assert "-main" not in flags


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

# Roles whose allowlist must never contain bare Bash while `forbidden` is set.
BARE_BASH = "Bash"


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


@dataclass
class Result:
    ok: bool
    value: Any = None
    error: str | None = None
    session_id: str = ""
    usage: list[UsageRecord] = field(default_factory=list)
    cost_usd: float | None = None       # CUMULATIVE when resuming (spec 7.5)


def infer(dispatch: Dispatch, executable: str = "claude") -> Result:
    """Perform one act of inference. Never retries — that is the caller's policy."""
    try:
        argv, cwd = _build(dispatch, executable)
    except InferenceError as exc:
        return Result(ok=False, error=str(exc))

    if shutil.which(executable) is None:
        return Result(
            ok=False,
            error=f"The `{executable}` CLI is not on PATH. Taller performs every "
                  f"act of inference through it.",
        )

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
        return Result(ok=False, error=str(payload.get("result", "unknown error")),
                      session_id=payload.get("session_id", ""))

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

    argv = [executable, "-p", "--output-format", "json", "--model", model]

    system = dispatch.system or _brief(dispatch, effort)
    if system:
        argv += ["--append-system-prompt", system]
    if dispatch.resume:
        argv += ["--resume", dispatch.resume]
    if dispatch.tools:
        argv += ["--allowedTools", ",".join(dispatch.tools)]
    if dispatch.forbidden:
        argv += ["--disallowedTools", ",".join(_expand_forbidden(dispatch.forbidden))]
    for directory in dispatch.writable:
        if str(directory).endswith("-main"):
            raise InferenceError(
                "The `main` worktree must never be writable by a dispatch; "
                "gitio.commit_to_main() is its only writer (spec 3.6.1)."
            )
        argv += ["--add-dir", str(directory)]
    if dispatch.schema is not None:
        argv += ["--json-schema", json.dumps(dispatch.schema)]
    if dispatch.agents is not None:
        argv += ["--agents", json.dumps(dispatch.agents)]
    if dispatch.unattended:
        argv += ["--permission-mode", "dontAsk"]
        if _supports_permission_prompts(executable):
            argv += ["--permission-prompts", "none"]

    # --bare is deliberately absent: it never reads OAuth credentials, so it
    # would silently require an API key (spec 3.6.2).
    return argv, cwd


def _brief(dispatch: Dispatch, effort: str) -> str:
    slices = (dispatch.ruleset or {}).get("slices") or {}
    parts = [f"/effort {effort}"]
    for resolved in slices.values():
        parts.append(resolved["text"] if isinstance(resolved, dict) else str(resolved))
    return "\n\n".join(p for p in parts if p)


def _expand_forbidden(globs: list[str]) -> list[str]:
    return [f"{tool}({glob})" for glob in globs for tool in WRITE_TOOLS]


_PERMISSION_PROMPTS: dict[str, bool] = {}


def _supports_permission_prompts(executable: str) -> bool:
    if executable not in _PERMISSION_PROMPTS:
        from . import cli_probe
        try:
            report = cli_probe.probe(executable)
            _PERMISSION_PROMPTS[executable] = report.supports("--permission-prompts")
        except Exception:
            _PERMISSION_PROMPTS[executable] = False
    return _PERMISSION_PROMPTS[executable]


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
    """
    cfg = dispatch.ruleset or dispatch.config
    concurrency = cfg.get("concurrency", {})
    thinker = cfg.get("model_aliases", {}).get("thinker")
    model = dispatch.model or config.resolve_model(dispatch.role, cfg)
    limit = (concurrency.get("max_parallel_thinker", 1) if model == thinker
             else concurrency.get("max_parallel_gates", 3))

    slots = paths.dispatch_slots()
    slots.mkdir(parents=True, exist_ok=True)
    from . import locking
    for index in range(max(1, limit)):
        lock = slots / f"slot-{index}.lock"
        try:
            with locking.file_lock(lock, timeout=0.05):
                yield
                return
        except Exception:
            continue
    # Every slot busy: wait for the first one rather than failing.
    with locking.file_lock(slots / "slot-0.lock", timeout=300):
        yield
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/unit/test_inference.py -q`
Expected: `17 passed`

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

    slots = paths.dispatch_slots()
    slots.mkdir(parents=True, exist_ok=True)

    # Occupy the single thinker slot from another process.
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import time
        from taller import locking
        with locking.file_lock({str(slots / 'slot-0.lock')!r}):
            time.sleep(4)
    """)])
    try:
        time.sleep(1.0)
        started = time.monotonic()
        inference.infer(_bootstrap_dispatch(role="architect"))  # thinker: limit 1
        waited = time.monotonic() - started
        assert waited >= 1.5, f"dispatch did not wait for the slot (waited {waited:.1f}s)"
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
- [ ] Confirm no test invoked the real binary: `grep -rn "subprocess" tests/ | grep -v stub` should show only the two deliberate second-process tests.
- [ ] Dispatch the plan reviewer on chunks 1–3 with the spec path, and fix what it finds before Chunk 4.

---

## Chunks 4–8: to be written after the review checkpoint

Remaining scope, in dependency order. Each becomes a chunk of the same shape once chunks 1–3 are approved:

| Chunk | Contents | Spec |
|---|---|---|
| **4** | The catalogue — three profiles, the module files with their required `> ` summary lines, three scaffolds with `manifest.yml` | §4.0, §4.1, §11.4 |
| **5** | `overrides.py` + the non-suppressible predicate; `constitution.py` — both chains, `resolve()`, `render_snapshot`, `render_index`, `render_tokens` | §4.3, §4.4, §4.5, §4.6, §3.1, §4.2.1 |
| **6** | `gitio.py` — `ensure_main_worktree()`, `commit_to_main()` with no-remote mode and the three `sync` states | §7.3 |
| **7** | `brands.py` (`from_pdf` first, it is the preferred source), `scaffold.py`, `discovery.py` | §4.2, §4.7, §11.4 |
| **8** | `cli.py`, the command modules, `doctor.py`, and the greenfield acceptance test of §15.5 | §3.5, §15.4, §15.5 |

The acceptance test in chunk 8 is the phase's real exit condition: `project new` against an empty `HOME`, once per catalogue profile, then `doctor` green with nothing skipped that Phase A provides.
