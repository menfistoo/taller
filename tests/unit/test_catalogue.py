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
