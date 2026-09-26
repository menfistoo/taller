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
