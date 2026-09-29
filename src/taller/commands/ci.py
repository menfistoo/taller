"""`taller ci`: the three model-free gates, run on GitHub's computers (spec 9.4).

A backstop, not a second opinion. It runs only the gates that need no model -
constitution, size, pytest - against the `.taller/resolved.json` the branch
already carries, so there is no hub to reach, no secret to hold, no model to
pay for, and the answer is the same one the owner's machine gave.

Anything that stops it seeing the real change - a base commit the checkout does
not have, a missing snapshot, a snapshot edited on the branch - exits 2. A
required check that passed because it compared nothing would be worse than
having no check at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import constitution, gates, overrides
from ..errors import TallerError
from ..gates import constitution as constitution_gate
from ..gates import diff as gate_diff
from ..gates import size as size_gate
from ..gates import tests as tests_gate
from ..prompter import Prompter
from .common import project_path

EXIT_PASS, EXIT_FINDINGS, EXIT_ERROR = 0, 1, 2
SNAPSHOT_FILES = (".taller/resolved.json", ".taller/constitution/00-index.md")
TICKET_FILES = ".taller/work/"
# What a finding looks like to GitHub: an annotation on the line it is about.
SEVERITY_LEVEL = {"BLOCKER": "error", "HIGH": "error", "MEDIUM": "warning",
                  "LOW": "notice", "NIT": "notice"}
FAILING = ("BLOCKER", "HIGH", "MEDIUM")


def annotations(findings: list[dict[str, Any]]) -> list[str]:
    """One GitHub annotation a finding, so it lands on the changed line itself."""
    out = []
    for found in findings:
        level = SEVERITY_LEVEL.get(found.get("severity", ""), "notice")
        where = []
        if found.get("file"):
            where.append(f"file={found['file']}")
            if found.get("line"):
                where.append(f"line={found['line']}")
        title = f"title={found['rule']}"
        message = " ".join(str(found.get("message") or "").split())
        out.append(f"::{level} {','.join([*where, title])}::{found['rule']}: {message}")
    return out


def run(args: Any, prompter: Prompter) -> int:
    project = project_path(getattr(args, "path", None))
    base, head = getattr(args, "base", None) or "origin/main", getattr(args, "head", None) or "HEAD"

    try:
        change = gate_diff.build(project, base, head)
    except RuntimeError as exc:
        prompter.say(f"The change could not be read: {exc}\n"
                     f"CI must see {base}..{head}; check out with `fetch-depth: 0` so the "
                     f"base commit is there.")
        return EXIT_ERROR

    listing = _changed_paths(project, base, head)
    if not listing:
        prompter.say(f"There is nothing to compare against {base}: no file differs between "
                     f"it and {head}. A first push has no earlier commit to measure from, "
                     f"so nothing was checked - push again once {base} exists, or give "
                     f"`--base` a commit that does.")
        return EXIT_ERROR
    # `diff.build` leaves ticket files out, so ask git itself what the push touched.
    if _only_ticket_files(project, base, head):
        prompter.say("This push changes ticket files only: nothing for the gates to check.")
        return EXIT_PASS
    if getattr(args, "mode", False):
        prompter.say("full")
        return EXIT_PASS

    carried = _generated_edited_on_the_branch(project, base, head)
    if carried:
        prompter.say(f"This branch changes {', '.join(carried)}, which only `taller resolve` "
                     f"writes on main (spec 4.6). Drop it from the branch; nothing is lost.")
        return EXIT_ERROR
    try:
        ruleset = constitution.load_snapshot(project)
    except TallerError as exc:
        prompter.say(str(exc))
        return EXIT_ERROR

    verdicts = [
        _safely("constitution", lambda: constitution_gate.run(change, ruleset)),
        _safely("size", lambda: size_gate.run(change, ruleset, tree=gate_diff.tree(project))),
        _safely("tests", lambda: tests_gate.run(project, ruleset)),
    ]
    # One `apply` for all of them: it appends its findings about the overrides
    # themselves on every call, and the constitution gate already reports those.
    own = [f for v in verdicts for f in v["findings"]]
    findings = overrides.apply(own, dict(ruleset))[:len(own)]
    errored = [v for v in verdicts if v["result"] == "error"]

    lines = [*annotations(findings)]
    for verdict in verdicts:
        detail = verdict.get("error") or f"{len(verdict['findings'])} finding(s)"
        lines.append(f"{verdict['gate']}: {verdict['result']} - {detail}")
    prompter.say("\n".join(lines))

    if errored:
        prompter.say("A gate could not run, so this push is not checked: "
                     + "; ".join(f"{v['gate']}: {v.get('error', '')}" for v in errored))
        return EXIT_ERROR
    if any(f.get("severity") in FAILING for f in findings):
        return EXIT_FINDINGS
    return EXIT_PASS


def mode(args: Any, prompter: Prompter) -> int:
    """`taller ci --mode`: `full` or `ticket-files`, the informational check (spec 9.4)."""
    project = project_path(getattr(args, "path", None))
    base, head = getattr(args, "base", None) or "origin/main", getattr(args, "head", None) or "HEAD"
    try:
        ticket_only = _only_ticket_files(project, base, head)
    except RuntimeError as exc:
        prompter.say(f"unknown - the change could not be read: {exc}")
        return EXIT_ERROR
    prompter.say("ticket-files" if ticket_only else "full")
    return EXIT_PASS


def _changed_paths(project: Path, base: str, head: str) -> list[str]:
    listing = gate_diff._git(project, "diff", "--name-only", "--no-renames",
                             f"{base}...{head}").decode("utf-8", errors="replace")
    return [line for line in listing.splitlines() if line.strip()]


def _only_ticket_files(project: Path, base: str, head: str) -> bool:
    changed = _changed_paths(project, base, head)
    return bool(changed) and all(path.startswith(TICKET_FILES) for path in changed)


def _generated_edited_on_the_branch(project: Path, base: str, head: str) -> list[str]:
    """The generated files a commit on this branch changed (spec 4.6).

    Asked of the branch's own commits, not of the tree difference: after an amend,
    `main` has a newer snapshot and `.gitattributes` keeps the branch's on purpose
    (`merge=ours`), so merging `main` in makes the file differ without anyone on
    the branch having touched it. Refusing that would be a merge nobody could ever
    complete.
    """
    edited = []
    for path in SNAPSHOT_FILES:
        commits = gate_diff._git(project, "log", "--format=%H", f"{base}..{head}", "--",
                                 path).decode("utf-8", errors="replace").split()
        if commits:
            edited.append(path)
    return edited


def _safely(name: str, runner: Any) -> dict[str, Any]:
    """A gate that crashed could not run: `result: error`, never a pass (spec 7.4)."""
    try:
        return runner()
    except Exception as exc:
        return {"gate": name, "result": "error", "findings": [], "metrics": {},
                "error": f"{type(exc).__name__}: {exc}"}
