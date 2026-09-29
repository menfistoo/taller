"""The CI workflow every project gets: two checks, always reporting, no secrets.

Spec 9.4 and 13. The required check must report a conclusion on every push, or a
pull request waits for ever; the informational one says whether the push was a
real change or only ticket files. Installing Taller needs no secret, because the
repository it comes from is public - and the address of it is the owner's
setting, never a name baked into what Taller ships.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import support
from taller import catalogue, config, discovery, paths, scaffold

WORKFLOW = ".github/workflows/taller-ci.yml"
TEMPLATE = Path(catalogue.__file__).resolve().parent / "catalogue" / "ci" / "taller-ci.yml"


def loaded(text: str) -> dict:
    return yaml.safe_load(text)


def test_the_shipped_template_names_no_account():
    text = TEMPLATE.read_text(encoding="utf-8")

    assert "%%install_taller%%" in text
    # Any address it shows is a placeholder: no real account is baked in, which
    # `test_publishing` proves for every tracked file.
    for line in text.splitlines():
        if "github.com/" in line:
            assert "<account>" in line, line


def test_both_check_names_are_there_and_the_required_one_always_runs():
    data = loaded(scaffold.ci_workflow("taller").decode("utf-8"))

    jobs = data["jobs"]
    assert jobs["gates"]["name"] == "taller-ci"
    assert jobs["mode"]["name"] == "taller-ci-mode"
    assert "paths-ignore" not in yaml.dump(data)
    assert all(step.get("with", {}).get("fetch-depth") == 0
               for job in jobs.values() for step in job["steps"]
               if "checkout" in str(step.get("uses", "")))


def test_it_installs_taller_without_a_secret():
    text = scaffold.ci_workflow("taller @ git+https://example.invalid/t@main").decode("utf-8")

    assert "secrets." not in text
    assert "taller @ git+https://example.invalid/t@main" in text
    assert "ANTHROPIC_API_KEY" not in text


def test_the_two_jobs_call_the_two_commands():
    text = scaffold.ci_workflow("taller").decode("utf-8")

    assert "taller ci --base" in text and "taller ci --mode" in text


def test_the_source_comes_from_the_hub_setting(tmp_home: Path):
    # Shipped unset, because a default would have to name somebody's account - and
    # a bare `taller` would install whatever stranger holds that name on PyPI.
    assert config.SHIPPED_DEFAULTS["ci"]["taller_source"] == ""
    assert scaffold.configured_taller_source() == ""

    support.write(paths.hub_config(), "ci:\n  taller_source: taller @ git+file:///t\n")

    assert scaffold.configured_taller_source() == "taller @ git+file:///t"


@pytest.fixture
def home(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    return tmp_home


def test_a_new_project_has_the_workflow(home):
    project = support.new_project()

    text = (project / WORKFLOW).read_text(encoding="utf-8")
    assert loaded(text)["jobs"]["gates"]["name"] == "taller-ci"
    assert support.git(project, "ls-files", "--", WORKFLOW).strip() == WORKFLOW
