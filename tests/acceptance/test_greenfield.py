"""Spec 15.5 and criterion 2: `taller project new` on an EMPTY hub, per profile.

Step 1 is the important one. A test run against a populated hub would pass while
`project new` silently depended on something a real first-time install does not
have. So HOME starts empty, the real command runs, and `taller doctor` must then
pass every phase A check with none of them skipped.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from taller import cli, discovery, doctor, paths
from taller.commands import brand as brand_command
from taller.prompter import ScriptedPrompter

SETUP = {"setup.billing": "", "setup.host": "", "setup.language.code": "en",
         "setup.language.ui": "es", "setup.language.commits": "en"}
FIRST_VERSION = ["List the tools", "Record a loan", "Show who has what"]
INTERVIEW = {
    "q1": "Tracks which neighbour has borrowed which shared tool.",
    "q2": "A marketplace: nothing is bought, sold or rented.",
    "q3": "Knowing who has which tool right now.",
    "q4": "1",                  # you alone -> no auth scaffolding
    "q5": "", "q6": "",
    "q7": "Tools, neighbours and loans.",
    "q8": "n",                  # no money or personal data -> no audit logging
    "q11": "1",                 # this machine only -> no container files
    "q12": FIRST_VERSION,
}
# A brand made from scratch, inside ⑩: the hub has none to pick.
NEW_BRAND = {
    "brand.slug": "harbour", "brand.start": "4",
    "brand.scratch.color-primary": "#1b365d", "brand.scratch.color-accent": "#c8a45c",
    "brand.scratch.color-success": "", "brand.scratch.color-warning": "",
    "brand.scratch.color-danger": "", "brand.scratch.color-surface": "",
    "brand.scratch.color-text": "", "brand.scratch.font-body": "",
    "brand.scratch.font-heading": "", "brand.scratch.space-unit": "",
    "brand.tokens": "", "brand.intent": "Calm navy; gold for the one action.",
    "brand.approve": "1",
}
# On an empty hub the profile picker is the catalogue, alphabetically.
CASES = [
    ("flask-sqlite", {"q9": "1", "q10": "2", **NEW_BRAND}, True),
    ("python-packaged", {"q9": "2", "q10": ""}, False),       # defaults to no brand
    ("static-site", {"q9": "3", "q10": "2", **NEW_BRAND}, True),
]


@pytest.mark.parametrize("profile, answers, branded", CASES, ids=[c[0] for c in CASES])
def test_project_new_on_an_empty_hub_passes_doctor(
    tmp_home: Path, stub_claude, identity, monkeypatch, profile, answers, branded,
):
    monkeypatch.setattr(brand_command, "open_in_browser", lambda page: None)
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    assert not paths.hub().exists(), "the hub is not empty"
    projects = paths.home() / "projects"

    # 1-2. The real command, scripted answers, an empty hub.
    prompter = ScriptedPrompter({**SETUP, **INTERVIEW, **answers, "brief": "1"})
    code = cli.main(["project", "new", "toolshed", "--path", str(projects), "--no-open"],
                    prompter)
    assert code == 0, "\n".join(prompter.said)
    prompter.assert_all_used()
    project = projects / "toolshed"

    # 3. Doctor: green, nothing phase A skipped except tokens for a brandless project.
    assert cli.main(["doctor"], ScriptedPrompter({})) == 0
    checks = doctor.run_checks()
    assert [c.name for c in checks if c.status == doctor.FAIL] == []
    skipped = [c.name for c in checks if c.status == doctor.SKIP and c.phase == "A"]
    assert skipped == ([] if branded else ["toolshed: brand tokens current"])

    # 5. Answer 12 is the queue, in the owner's words; no ticket folders yet.
    queue = yaml.safe_load(paths.project_queue(project).read_text(encoding="utf-8"))
    assert [entry["title"] for entry in queue["proposed"]] == FIRST_VERSION
    assert not (project / ".taller" / "work").exists()

    # 6. The manifest omissions held.
    for absent in ("docker-compose.yml", "docker-compose.staging.yml", "Dockerfile",
                   "auth.py", "audit.py"):
        assert not (project / absent).exists(), absent

    # The generated project's own suite is green.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p",
                                "no:cacheprovider"], cwd=project, capture_output=True,
                               text=True, env=env)
    assert completed.returncode == 0, completed.stdout + completed.stderr
