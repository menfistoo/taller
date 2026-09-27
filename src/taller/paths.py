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


def swatch(slug: str) -> Path:
    """A brand's review page (spec 4.2): opened locally, never committed."""
    return run_dir() / "swatches" / f"{slug}.html"


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
