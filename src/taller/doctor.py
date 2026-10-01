"""`taller doctor`: every check spec 15.4 lists, pass / fail / skip-with-reason.

Doctor is meaningful before every phase exists: a check whose machinery belongs
to a later phase is **skipped with the phase that brings it**, never silently
omitted and never passed. It reads and never repairs — each failure names the
command that fixes it. The one thing it may write is the cache of its live
dispatch check, so that check does not spend the subscription window on every
run.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import (catalogue, cli_probe, config, constitution, generated, gitio, inference,
               locking, overrides, paths, registry)
from .errors import TallerError

PASS, FAIL, SKIP = "pass", "fail", "skip"
DISPATCH_CACHE_TTL = timedelta(hours=24)
# A trivial dispatch answers in seconds. Past this, report it rather than hang.
DISPATCH_CHECK_TIMEOUT = 120.0
API_KEY_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

# Spec 15.4's rows that later phases bring. Listed so the report shows them.
LATER: tuple[tuple[str, str], ...] = ()


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    phase: str = "A"
    fix: str = ""


def run_checks(*, live: bool = False) -> list[Check]:
    checks = [_cli(), _dispatch(live), _models(), _billing(), *_profiles(), _locks(),
              _registry()]
    try:
        projects = registry.list_projects()
    except TallerError:
        projects = []                      # already reported by _registry
    for entry in projects:
        checks.extend(_project(entry))
    checks.extend(Check(name, SKIP, f"arrives in phase {phase}", phase)
                  for name, phase in LATER)
    return checks


# --- hub-wide ----------------------------------------------------------------

def _cli() -> Check:
    name = "claude CLI present, recent enough, every flag accepted"
    try:
        report = cli_probe.probe()
    except TallerError as exc:
        return Check(name, FAIL, str(exc), fix="Install Claude Code, then `claude` once.")
    minimum = config.load_hub_config()["cli_min_version"]
    version = ".".join(map(str, report.version)) if report.version else "unknown"
    if not cli_probe.version_at_least(report.version, minimum):
        return Check(name, FAIL, f"version {version}, need {minimum}",
                     fix="Update Claude Code.")
    if not report.ok:
        return Check(name, FAIL, f"missing flags: {', '.join(report.missing_required)}",
                     fix="Update Claude Code.")
    return Check(name, PASS, f"version {version}")


def _dispatch(live: bool) -> Check:
    """A trivial dispatch with no API key in its environment (spec 3.6.2).

    Proves the subscription still authenticates and that nothing has quietly
    switched Taller onto per-token billing. Cached for a day: the check is real
    inference, and doctor is meant to be free to run.
    """
    name = "a dispatch succeeds on the subscription, with no API key"
    cache = paths.doctor_dispatch_cache()
    if not live:
        passed_at = _cached_pass(cache)
        if passed_at:
            return Check(name, PASS, f"passed {passed_at:%Y-%m-%d %H:%M} UTC; "
                                     f"`taller doctor --live` re-checks")
    result = inference.infer(inference.Dispatch(
        role="explorer", prompt="Reply with the single word OK.",
        config=config.load_hub_config(), unset_env=API_KEY_VARIABLES,
        timeout=DISPATCH_CHECK_TIMEOUT,
    ))
    if not result.ok:
        return Check(name, FAIL, result.error or "the dispatch failed",
                     fix="Run `claude -p \"say OK\" --model haiku` yourself: if it also "
                         "hangs or fails, update Claude Code (`claude update`) and sign "
                         "in again with your subscription.")
    locking.atomic_write_text(cache, json.dumps(
        {"passed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}) + "\n")
    return Check(name, PASS, "dispatched just now")


def _cached_pass(cache: Path) -> datetime | None:
    try:
        passed_at = datetime.fromisoformat(json.loads(cache.read_text(encoding="utf-8"))
                                           ["passed_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return passed_at if datetime.now(timezone.utc) - passed_at < DISPATCH_CACHE_TTL else None


def _models() -> Check:
    """Spec 15.4, phase B: every configured model answered the last probe."""
    from . import models

    name = "every configured model reachable (last `taller models probe`)"
    record = models.load_probe()
    if record is None:
        return Check(name, SKIP, "never probed: `taller models probe` checks them", phase="B")
    cfg = config.load_hub_config()
    down = [m for m in models.configured(cfg) if models.reachable(m, record) is False]
    unknown = [m for m in models.configured(cfg) if models.reachable(m, record) is None]
    if down or unknown:
        detail = "; ".join(filter(None, [
            f"not reachable: {', '.join(down)}" if down else "",
            f"not probed: {', '.join(unknown)}" if unknown else ""]))
        return Check(name, FAIL, detail, phase="B",
                     fix="`taller models probe`; if a model stays unreachable, point its "
                         "alias elsewhere with `taller settings set model_aliases.<alias> <model>`.")
    return Check(name, PASS, f"probed {record.get('at', '')}", phase="B")


def _billing() -> Check:
    """Spec 15.4, phase B: the configured mode matches the environment (5.2)."""
    from datetime import date

    from . import billing

    name = "billing mode matches the environment; pricing not stale"
    problem = billing.mismatch()
    if problem:
        return Check(name, FAIL, problem, phase="B",
                     fix="`taller settings set billing.mode <mode>`, or unset the variable.")
    cfg = config.load_hub_config()
    detail = f"mode {billing.mode(cfg)}"
    age = billing.pricing_age_days(cfg, date.today())
    if billing.mode(cfg) == "api" and age is not None and age > 90:
        detail += f"; the price table is {age} days old (advisory: costs use it anyway)"
    return Check(name, PASS, detail, phase="B")


def _profiles() -> list[Check]:
    checks = []
    for name in catalogue.installed_profiles():
        missing = catalogue.missing_modules(name)
        checks.append(Check(
            f"profile {name} names only modules the hub has",
            FAIL if missing else PASS,
            f"missing: {', '.join(missing)}" if missing else "",
            fix="Restore the module files, or `taller setup`." if missing else "",
        ))
        # An installed profile is never overwritten, so a Taller that gains a
        # setting leaves this hub without it until the owner asks for it.
        gaps = catalogue.profile_gaps(name)
        checks.append(Check(
            f"profile {name} is current with this version of Taller",
            FAIL if gaps else PASS,
            f"predates this Taller; it has no {', '.join(gaps)}" if gaps else "",
            fix=f"`taller profiles update {name}` adds them and keeps your own edits."
                if gaps else "",
        ))
    return checks


def _locks() -> Check:
    name = "no lock left behind by a dead process"
    candidates = [paths.hub_lock(), paths.registry_lock(),
                  *sorted((paths.run_dir() / "locks").glob("*.lock")),
                  *sorted(paths.dispatch_slots().rglob("*.lock"))]
    stale = [str(path) for path in candidates if path.is_file() and locking.is_stale(path)]
    if stale:
        return Check(name, FAIL, "; ".join(stale),
                     fix="No Taller process is running: delete those files.")
    return Check(name, PASS)


def _registry() -> Check:
    name = "registry valid; every registered path exists"
    try:
        missing = registry.missing_paths()
    except TallerError as exc:
        return Check(name, FAIL, str(exc), fix=f"Repair {paths.registry()}.")
    if missing:
        return Check(name, FAIL, f"missing: {', '.join(missing)}",
                     fix="Move it back, or remove it from the registry.")
    return Check(name, PASS, f"{len(registry.list_projects())} registered")


# --- per project -------------------------------------------------------------

def _project(entry: dict[str, Any]) -> list[Check]:
    label = entry["name"]
    repo = Path(entry["path"])
    if not repo.is_dir():
        return []                                      # reported by _registry
    if not registry.is_adopted(entry):
        # Decision B1: registered by `setup`, nothing written into it yet. Not a
        # fault, and not a pass either: there is nothing of Taller's to check.
        return [Check(f"{label}: not adopted yet", SKIP,
                      f"`taller project adopt {repo}` when you are ready")]
    checks: list[Check] = []

    worktree = paths.main_worktree(label)
    checks.append(Check(f"{label}: main worktree present",
                        PASS if gitio._is_worktree(worktree) else FAIL, str(worktree),
                        fix="`taller resolve` recreates it."))
    checks.append(_tickets(label, repo))

    try:
        ruleset = constitution.resolve(repo)
    except TallerError as exc:
        checks.append(Check(f"{label}: resolve() succeeds", FAIL, str(exc)))
        return checks + [_merge_driver(label, repo)]

    language = ruleset.get("language")
    checks.append(Check(f"{label}: language set",
                        PASS if isinstance(language, dict) and language.get("code") else FAIL,
                        fix="`taller setup`."))

    problems = overrides.apply([], ruleset)
    checks.append(Check(
        f"{label}: resolve() succeeds; overrides reasoned, current and permitted",
        FAIL if problems else PASS,
        "; ".join(f"{p['rule']}: {p['message']}" for p in problems),
        fix="Edit .taller/constitution/overrides.md." if problems else "",
    ))

    expected = generated.render_all(repo, ruleset)
    checks.append(_snapshot(label, repo, expected, ruleset))
    checks.append(_index(label, repo, expected))
    checks.append(_tokens(label, repo, expected, ruleset))
    checks.append(_merge_driver(label, repo))
    checks.append(_branches(label, repo, expected))
    checks.append(_gates(label, repo, ruleset))
    checks.extend(_github(label, repo))
    return checks


def _github(label: str, repo: Path) -> list[Check]:
    """Spec 15.4's F row, and spec 13's branch protection. Read-only, and a project
    without a GitHub remote skips both: nothing here is required to use Taller."""
    from . import github, issues, scaffold

    names = (f"{label}: latest taller-ci run on main was green",
             f"{label}: merging requires a pull request and a green taller-ci",
             f"{label}: CI can install Taller")
    remote = issues.repo_of(repo)
    if remote is None:
        return [Check(name, SKIP, "no GitHub remote; Taller works without one", phase="F")
                for name in names]

    ci = github.latest_ci(repo, remote)
    rule = github.protection(remote)
    status = {"green": PASS, "failed": FAIL}.get(ci["state"], SKIP)
    protected = {True: PASS, False: FAIL, None: SKIP}[rule["ok"]]
    source = scaffold.configured_taller_source(repo)
    return [
        Check(names[0], status, ci["detail"], phase="F",
              fix="Open the run on GitHub and read the annotations on the diff."
                  if status == FAIL else ""),
        Check(names[1], protected, rule["detail"], phase="F",
              fix=f"`taller github protect --path {repo}` prints what to turn on."
                  if protected == FAIL else ""),
        Check(f"{label}: CI can install Taller", PASS if source.strip() else FAIL,
              source or "ci.taller_source is not set, so the checks cannot run on GitHub",
              phase="F",
              fix="`taller settings set ci.taller_source \"taller @ git+<your Taller "
                  "repository>\"`, then `taller resolve` in each project to rewrite its "
                  "workflow." if not source.strip() else ""),
    ]


def _gates(label: str, repo: Path, ruleset: dict[str, Any]) -> Check:
    """Spec 15.4, phase C: every Python gate executes on an empty diff; the smoke
    configuration is usable, its secret included; each model gate dry-runs.

    The tests gate is not run - that would run the project's whole suite - but
    its interpreter must exist and import pytest.
    """
    from .gates import constitution as constitution_gate
    from .gates import llm, size, smoke
    from .gates import tests as tests_gate

    name = f"{label}: every gate executes; smoke configuration valid"
    problems: list[str] = []
    empty = {"base": "", "head": "", "commits": [], "files": [], "tracked": []}
    for gate, check in (("constitution", constitution_gate.run), ("size", size.run)):
        try:
            check(empty, ruleset)
        except Exception as exc:              # a crash here is the finding
            problems.append(f"the {gate} gate raised {type(exc).__name__}: {exc}")
    python = tests_gate.interpreter(repo)
    if not Path(python).is_file():
        problems.append(python)
    else:
        try:
            ran = subprocess.run([python, "-c", "import pytest"], capture_output=True,
                                 timeout=60)
            if ran.returncode != 0:
                problems.append(f"pytest is not installed for {python}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            problems.append(f"{python} could not be run: {exc}")
    problems.extend(smoke.problems(ruleset.get("smoke")))
    cfg = config.load_hub_config()
    for gate in llm.GATES:
        problem = llm.dry_run(gate, ruleset, cfg)
        if problem:
            problems.append(problem)
    if problems:
        return Check(name, FAIL, "; ".join(problems), phase="C",
                     fix="Fix the smoke block in taller.yml or the profile, set the named "
                         "variable, or install what is missing.")
    return Check(name, PASS, phase="C")


def _tickets(label: str, repo: Path) -> Check:
    """Spec 15.4, phase D: every status.yml parses; nothing left `sync: pending`.

    `local` - no remote at all - is fine. Read from `main`, where tickets live.
    """
    from . import tickets

    name = f"{label}: tickets readable; none left unpushed"
    found, problems = tickets.list_tickets(repo)
    unpushed = [f"{t['id']:04d}" for t in found
                if tickets.effective_sync(repo, t) == "pending"]
    if problems:
        return Check(name, FAIL, "; ".join(problems), phase="D",
                     fix="Repair the file on main, or `git revert` the commit that broke it.")
    if unpushed:
        return Check(name, FAIL, f"not pushed: {', '.join(unpushed)}", phase="D",
                     fix="Check the remote is reachable; the next ticket command pushes "
                         "everything waiting, and this check then passes.")
    held = sum(1 for t in found if tickets.effective_sync(repo, t) == "held")
    detail = f"{len(found)} tickets" + (f"; {held} waiting for you to publish" if held else "")
    return Check(name, PASS, detail, phase="D")


def _on_main(repo: Path, relative: str) -> bytes | None:
    completed = subprocess.run(["git", "-C", str(repo), "cat-file", "blob",
                                f"{gitio.MAIN_BRANCH}:{relative}"], capture_output=True)
    return completed.stdout if completed.returncode == 0 else None


def _snapshot(label: str, repo: Path, expected: dict[str, bytes], ruleset: dict) -> Check:
    """Spec 4.6's order: absent, then stale, then modified."""
    name = f"{label}: resolved.json current and untampered"
    committed = _on_main(repo, generated.SNAPSHOT)
    if committed is None:
        return Check(name, FAIL, "not on main", fix="`taller resolve`.")
    try:
        recorded = json.loads(committed.decode("utf-8")).get("hub_sha")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return Check(name, FAIL, "not valid JSON", fix="`taller resolve`.")
    if recorded != ruleset.get("hub_sha"):
        return Check(name, FAIL, "stale: the hub has changed since it was resolved",
                     fix="`taller resolve`.")
    if committed != expected[generated.SNAPSHOT]:
        return Check(name, FAIL, "modified: it differs from a fresh resolution",
                     fix="`taller resolve`, and find out who edited it.")
    return Check(name, PASS)


def _index(label: str, repo: Path, expected: dict[str, bytes]) -> Check:
    name = f"{label}: 00-index.md current and within its budget"
    committed = _on_main(repo, generated.INDEX)
    if committed is None:
        return Check(name, FAIL, "not on main", fix="`taller resolve`.")
    if committed != expected[generated.INDEX]:
        return Check(name, FAIL, "differs from a fresh render", fix="`taller resolve`.")
    tokens = constitution.estimate_tokens(committed.decode("utf-8"))
    return Check(name, PASS, f"≈{tokens} of {constitution.INDEX_TOKEN_BUDGET} tokens")


def _tokens(label: str, repo: Path, expected: dict[str, bytes], ruleset: dict) -> Check:
    name = f"{label}: brand tokens current"
    if ruleset.get("brand") is None:
        return Check(name, SKIP, "the project's brand is none")
    path = next((p for p in expected if p not in (generated.SNAPSHOT, generated.INDEX)), None)
    if path is None:
        return Check(name, FAIL, "the profile sets no paths.brand_tokens",
                     fix="Set paths.brand_tokens, or choose brand none.")
    committed = _on_main(repo, path)
    if committed != expected[path]:
        return Check(name, FAIL, f"{path} is missing or differs from the hub brand",
                     fix="`taller resolve`.")
    return Check(name, PASS, path)


def _merge_driver(label: str, repo: Path) -> Check:
    value = gitio.git(repo, "config", "merge.ours.driver", check=False).stdout.strip()
    return Check(f"{label}: merge.ours.driver configured",
                 PASS if value else FAIL,
                 fix="git config merge.ours.driver true" if not value else "")


def _branches(label: str, repo: Path, expected: dict[str, bytes]) -> Check:
    name = f"{label}: no branch carries its own generated files"
    branches = gitio.git(repo, "for-each-ref", "--format=%(refname:short)",
                         "refs/heads/").stdout.split()
    offenders = []
    for branch in branches:
        if branch == gitio.MAIN_BRANCH:
            continue
        touched = gitio.git(repo, "log", f"{gitio.MAIN_BRANCH}..{branch}", "--name-only",
                            "--format=").stdout.split()
        carried = sorted(set(touched) & set(expected))
        if carried:
            offenders.append(f"{branch} ({', '.join(carried)})")
    if offenders:
        return Check(name, FAIL, "; ".join(offenders),
                     fix="Remove those commits from the branch; main owns these files.")
    return Check(name, PASS)


# --- report ------------------------------------------------------------------

def render(checks: list[Check]) -> str:
    marks = {PASS: "pass", FAIL: "FAIL", SKIP: "skip"}
    lines = []
    for check in checks:
        line = f"  {marks[check.status]:4}  {check.name}"
        if check.detail:
            line += f" — {check.detail}"
        lines.append(line)
        if check.status == FAIL and check.fix:
            lines.append(f"        fix: {check.fix}")
    failed = sum(check.status == FAIL for check in checks)
    lines.append("")
    lines.append(f"{failed} failed." if failed else "All checks pass.")
    return "\n".join(lines)
