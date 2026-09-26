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
