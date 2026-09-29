"""What GitHub says about a project, and the rule the owner should turn on.

Spec 13. Read-only, on purpose: Taller never edits a setting on her account (her
decision, 2026-09-29). It reports, and names the exact thing to switch on.

**Why "the latest run that was a real change".** Almost every commit on `main` is
one of Taller's own ticket-file commits, whose CI run exits at once (spec 9.4).
"The latest run is green" would therefore be true and mean nothing. §15.4 asks
for the latest run whose push was `full`; Taller works that out from the commit
itself, which it can see, rather than from the informational check's log.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import discovery, gitio, issues

WORKFLOW = "taller-ci.yml"
CHECK = "taller-ci"
TICKET_FILES = ".taller/work/"
RUNS_READ = 20              # far enough back to pass the ticket-file commits


def latest_ci(project: Path | str, repo: str) -> dict[str, Any]:
    """`{"state": green|failed|none|unknown, "detail": str}` for the latest real change."""
    completed = discovery._run_gh(["run", "list", "--repo", repo, "--branch",
                                   gitio.MAIN_BRANCH, "--workflow", WORKFLOW,
                                   "--limit", str(RUNS_READ), "--json",
                                   "conclusion,status,headSha,createdAt"])
    if completed is None:
        return {"state": "unknown", "detail": "gh is not installed, so GitHub cannot be asked"}
    if completed.returncode != 0:
        return {"state": "unknown", "detail": issues._failure(completed)}
    try:
        entries = json.loads(completed.stdout or "[]")
    except ValueError:
        return {"state": "unknown", "detail": "gh did not answer with JSON"}
    if not entries:
        return {"state": "none", "detail": f"no {CHECK} run on {gitio.MAIN_BRANCH} yet"}

    unseen = 0
    for entry in entries:
        sha = str(entry.get("headSha") or "")
        touched = _touched_outside_ticket_files(project, sha)
        if touched is None:
            unseen += 1
            continue                      # not in this checkout: cannot judge it
        if not touched:
            continue                      # a ticket-file push: its run proves nothing
        if str(entry.get("status") or "") != "completed":
            return {"state": "unknown",
                    "detail": f"{sha[:7]} is still running"}
        return _required_check(repo, sha, str(entry.get("conclusion") or ""))
    if unseen:
        return {"state": "unknown",
                "detail": f"the last {unseen} run(s) are on commits this checkout does not "
                          f"have; fetch, or push what is local"}
    return {"state": "none",
            "detail": f"every recent run was a ticket-file push, which proves nothing"}


def _required_check(repo: str, sha: str, run_conclusion: str) -> dict[str, Any]:
    """The verdict of the `taller-ci` check itself, not of the whole run.

    The run's conclusion is the aggregate of both jobs, and `taller-ci-mode` is
    deliberately not required (spec 9.4): a failure there must not be reported as
    a failed check.
    """
    completed = discovery._run_gh(["api", f"repos/{repo}/commits/{sha}/check-runs"])
    if completed is not None and completed.returncode == 0:
        try:
            runs = json.loads(completed.stdout or "{}").get("check_runs") or []
        except ValueError:
            runs = []
        for check in runs:
            if str(check.get("name")) != CHECK:
                continue
            if str(check.get("status") or "") != "completed":
                return {"state": "unknown", "detail": f"{sha[:7]}: {CHECK} is still running"}
            conclusion = str(check.get("conclusion") or "")
            return {"state": "green" if conclusion == "success" else "failed",
                    "detail": f"{sha[:7]}: {CHECK} {conclusion or 'did not report'}"}
    # No check-run answer: fall back to the run's own conclusion.
    return {"state": "green" if run_conclusion == "success" else "failed",
            "detail": f"{sha[:7]} {run_conclusion or 'did not report'}"}


def protection(repo: str) -> dict[str, Any]:
    """Whether the default branch requires a pull request and a green `taller-ci`.

    `ok: None` means GitHub could not be asked - offline, no `gh`, or a repository
    she does not administer. That is not the same as "not protected", and doctor
    must not call it a failure.
    """
    listed = discovery._run_gh(["api", f"repos/{repo}/rulesets"])
    if listed is None:
        return {"ok": None, "detail": "gh is not installed, so GitHub cannot be asked"}
    if listed.returncode != 0:
        return {"ok": None, "detail": issues._failure(listed)}
    try:
        rulesets = json.loads(listed.stdout or "[]")
    except ValueError:
        return {"ok": None, "detail": "gh did not answer with JSON"}

    missing = {"a pull request", f"a green {CHECK}"}
    for ruleset in rulesets if isinstance(rulesets, list) else []:
        if not missing:
            break                         # both requirements found; stop asking
        if ruleset.get("target") not in (None, "branch"):
            continue
        detail = discovery._run_gh(["api", f"repos/{repo}/rulesets/{ruleset.get('id')}"])
        if detail is None or detail.returncode != 0:
            continue
        try:
            rules = json.loads(detail.stdout or "{}").get("rules") or []
        except ValueError:
            continue
        kinds = {str(rule.get("type")) for rule in rules}
        if "pull_request" in kinds:
            missing.discard("a pull request")
        for rule in rules:
            if rule.get("type") != "required_status_checks":
                continue
            checks = (rule.get("parameters") or {}).get("required_status_checks") or []
            if any(str(check.get("context")) == CHECK for check in checks):
                missing.discard(f"a green {CHECK}")
    if missing:
        return {"ok": False, "detail": "the default branch does not require "
                                       + " or ".join(sorted(missing))}
    return {"ok": True, "detail": f"a pull request and a green {CHECK} are required"}


def ruleset_instructions(repo: str) -> str:
    """The exact thing to turn on. Taller will not do it for her."""
    return "\n".join([
        f"To protect {gitio.MAIN_BRANCH} on {repo}, turn this on yourself - Taller will not "
        f"change a setting on your GitHub account:",
        "",
        f"  GitHub → {repo} → Settings → Rules → Rulesets → New branch ruleset",
        f"    Target: the default branch",
        f"    Require a pull request before merging",
        f"    Require status checks to pass: {CHECK}",
        "",
        "And in Settings → General → Pull Requests, leave **Rebase and merge** on.",
        "Taller recognises a rebase, a squash and an ordinary merge, but a rebase",
        "keeps `main` readable and is what these instructions assume.",
        "",
        "Or, in a terminal:",
        "",
        f"  gh api --method POST repos/{repo}/rulesets --input ruleset.json",
        "",
        "with ruleset.json:",
        "",
        json.dumps({
            "name": "taller", "target": "branch", "enforcement": "active",
            "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
            "rules": [
                {"type": "pull_request"},
                {"type": "required_status_checks",
                 "parameters": {"strict_required_status_checks_policy": False,
                                "required_status_checks": [{"context": CHECK}]}},
            ],
        }, indent=2),
        "",
        "Keep your own admin bypass: `gitio.commit_to_main()` writes ticket files to "
        f"{gitio.MAIN_BRANCH} directly (spec 13).",
    ])


def _touched_outside_ticket_files(project: Path | str, sha: str) -> bool | None:
    """True when that commit changed something real; None when it is not here."""
    if not sha:
        return None
    if gitio.git(project, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode:
        return None
    # `--first-parent -m` so a MERGE commit lists what it brought in: `diff <sha>^!`
    # prints nothing at all for a merge, which read as "a ticket-file push" and made
    # doctor skip every normally-merged change on main.
    listing = gitio.git(project, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m",
                        "--first-parent", sha, check=False)
    if listing.returncode:
        return None
    changed = [line for line in listing.stdout.splitlines() if line.strip()]
    return any(not path.startswith(TICKET_FILES) for path in changed)
