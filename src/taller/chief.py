"""The chief: one ticket, carried from where it is to the next point that needs the owner.

Spec 3.1, 7.6, 8. `run` owns the loop and holds the project lock for all of it,
so the CLI, a second terminal and the cockpit cannot drive one ticket at once
(7.6). Everything the spec states as a rule is decided here in Python - the lane
(8.2), promotion at ④, the budget (7.5), the fallback (14) - and inference is
used only where judgement is: classifying the owner's words, surveying the
code, planning, building, summarising. Every dispatch's usage is folded into
the ticket as soon as it returns.

⑤ runs the gates §9.2 selects and ⑥ the smoke check (spec 9); each finding goes
where its rule says - a fixer round, a deterministic command, or the owner. The
⑧ opens the pull request the branch has earned (spec 13); a project with no
GitHub remote is merged by the owner herself, as before. Every owner checkpoint
still holds.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Mapping

from . import (config, constitution, gates, generated, gitio, globs, inference, locking,
               models, overrides, prs, registry, roles, spend, tickets)
from .gates import constitution as constitution_gate
from .gates import diff as gate_diff
from .gates import llm
from .gates import size as size_gate
from .gates import smoke as smoke_gate
from .gates import tests as tests_gate
from .errors import ConfigError, TallerError
from .scaffold import flatten

Ticket = dict[str, Any]
Say = Callable[[str], None]

_MERGE_NOTE = "⑧ pull request stage: waiting for the branch to be merged"
# The fixer may never touch a test (spec 9.7), nor switch one off from pytest's
# configuration; a round whose diff does is undone.
TEST_FILES = ("test_*.py", "*_test.py")
TEST_CONFIG = ("conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini")
SNAPSHOT = ".taller/resolved.json"
UNAVAILABLE = models.UNAVAILABLE
DIFF_IGNORED = ".taller/work/"


class Blocked(TallerError):
    """A stage cannot go on without the owner; the reason goes on the ticket."""


# --- lanes (8.2) ------------------------------------------------------------------

def _security_hit(paths: list[str], ruleset: Mapping[str, Any]) -> tuple[str, str] | None:
    """The first changed path matching a security-sensitive glob, gitignore-style."""
    patterns = ((ruleset.get("paths") or {}).get("security_sensitive")) or []
    for path in paths:
        pattern = globs.any_match(path, patterns)
        if pattern:
            return path, pattern
    return None


def decide_lane(facts: Mapping[str, Any], ruleset: Mapping[str, Any]) -> tuple[str, str]:
    """(lane, reason). `fast` needs all seven of §8.2's conditions; doubt is `full`."""
    files = list(facts.get("files") or [])
    hit = _security_hit(files, ruleset)
    checks = [
        (hit is not None, f"{hit[0]} matches the security-sensitive glob {hit[1]}" if hit else ""),
        (bool(facts.get("adds_or_deletes_files")), "a file is added or deleted"),
        (bool(facts.get("schema_change")), "the database schema changes"),
        (bool(facts.get("route_change")), "a route is added or removed"),
        (bool(facts.get("dependency_change")), "a dependency changes"),
        (len(files) != 1, f"{len(files)} files would change, not one"),
        (facts.get("change_kind") not in ("literal", "string", "style", "threshold"),
         "it is more than a literal, string, style or threshold edit"),
    ]
    for failed, reason in checks:
        if failed:
            return "full", reason
    return "fast", f"one file ({files[0]}), a {facts.get('change_kind')} edit"


def needs_promotion(diff: Mapping[str, Any], ticket: Mapping[str, Any],
                    ruleset: Mapping[str, Any]) -> str | None:
    """Why a fast ticket's actual diff at ④ breaks a fast bound (8.2), or None."""
    if ticket.get("lane") != "fast":
        return None
    files = diff.get("files") or []
    limit = int((ruleset.get("thresholds") or {}).get("max_fast_lane_lines", 50))
    added = [f["path"] for f in files if f["status"] in ("A", "D")]
    hit = _security_hit([f["path"] for f in files], ruleset)
    lines = sum(f["lines"] for f in files)
    if added:
        return f"a file was added or deleted ({', '.join(added)})"
    if len(files) > 1:
        return f"{len(files)} files changed, not one"
    if lines > limit:
        return f"{lines} lines changed, over the fast lane's {limit}"
    if hit:
        return f"{hit[0]} matches the security-sensitive glob {hit[1]}"
    return None


def _diff(project: Path, branch: str) -> dict[str, Any]:
    """The branch's own change against `main`, ticket files excluded."""
    spec = f"{gitio.MAIN_BRANCH}...{branch}"
    status = dict(line.split("\t", 1)[::-1] for line in gitio.git(
        project, "diff", "--name-status", "--no-renames", spec).stdout.splitlines() if "\t" in line)
    files = []
    for line in gitio.git(project, "diff", "--numstat", "--no-renames", spec).stdout.splitlines():
        added, removed, path = (line.split("\t") + ["", "", ""])[:3]
        if not path or path.startswith(DIFF_IGNORED):
            continue
        count = sum(int(n) for n in (added, removed) if n.isdigit())
        files.append({"path": path, "status": status.get(path, "M")[:1], "lines": count})
    return {"files": files}


# --- dispatching ------------------------------------------------------------------

def _ask(project: Path, ticket_id: int, role: str, prompt: str, *, cfg: Mapping[str, Any],
         ruleset: Mapping[str, Any] | None, cwd: Path | None = None,
         writable: list[str] | None = None, resume: str | None = None
         ) -> tuple[Any, inference.Result]:
    """One role's answer, with §14's policy: one retry, one fallback, then block."""
    model: str | None = None
    fell_back = False
    last = ""
    attempt = 0
    while attempt < 2:
        # §7.5: a thinker dispatch checks the budget first, so the warning is
        # actionable before the expensive call rather than after it.
        if config.resolve_model(role, cfg) == cfg["model_aliases"].get("thinker") and \
                spend.budget(tickets.load(project, ticket_id), cfg) == "stop":
            raise Blocked(_budget_reason(tickets.load(project, ticket_id), cfg))
        result = inference.infer(inference.Dispatch(
            role=role, prompt=prompt, config=cfg, ruleset=ruleset, model=model,
            cwd=str(cwd) if cwd else None, writable=list(writable or []),
            schema=roles.SCHEMAS.get(role), resume=resume))
        if result.usage or result.ok:
            spend.fold(project, ticket_id, result, cfg)
        if not result.ok and not fell_back and UNAVAILABLE.search(result.error or ""):
            fallback = models.fallback_for(role, cfg)
            if fallback:
                fell_back = True
                requested = model or config.resolve_model(role, cfg)
                _record_fallback(project, ticket_id, role, requested, fallback)
                model = fallback
                continue                          # a fallback is not the retry
        problem = (result.error or "the dispatch failed") if not result.ok \
            else roles.check(role, result.value)
        if problem is None:
            return result.value, result
        last = problem
        attempt += 1
    raise Blocked(f"the {role} gave no usable answer twice: {last}")


def _record_fallback(project: Path, ticket_id: int, role: str, requested: str, used: str):
    ticket = tickets.load(project, ticket_id)
    ticket.setdefault("fallbacks", []).append({"role": role, "requested": requested,
                                               "used": used})
    tickets.write(project, ticket, f"ticket {ticket_id:04d}: fallback",
                  note=f"{role}: {requested} was unavailable; used {used}")


def _budget_reason(ticket: Mapping[str, Any], cfg: Mapping[str, Any]) -> str:
    spent = (ticket.get("spend") or {}).get("weighted_tokens", 0)
    stop = (cfg.get("budget") or {}).get("per_ticket_stop")
    return (f"the budget is spent: {spent} weighted tokens against a stop at {stop}. "
            f"Raise budget.per_ticket_stop with `taller settings set`, or close the ticket.")


NOTES_SHOWN = 40            # the ticket's history a role is shown, newest last
PATCH_SHOWN = 12_000       # characters of the diff a role is shown
GATE_PATCH_MAX = 200_000   # a gate judges the change, so it is shown (nearly) all of it


def _context(project: Path, ticket: Mapping[str, Any]) -> str:
    """What every role starts from: the owner's words and the ticket's history.

    The history is `notes.md`: lanes and why, rejections and their reasons,
    what the implementer said it did. §7.6 and §14 say a fresh attempt is
    "briefed from notes.md" - this is that briefing.
    """
    words = tickets._words(project, ticket).strip()
    raw = tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/notes.md") or b""
    notes = raw.decode("utf-8", errors="replace").strip().splitlines()[-NOTES_SHOWN:]
    text = f"Ticket {ticket['id']:04d}: {ticket['title']}\n\nThe owner's words:\n{words}\n"
    if notes:
        text += "\nWhat has happened so far:\n" + "\n".join(notes) + "\n"
    return text


def _change(project: Path, ticket: Mapping[str, Any], limit: int = PATCH_SHOWN) -> str:
    """The branch's change against `main` - stat, then the patch, capped."""
    if not ticket.get("branch"):
        return ""
    spec = f"{gitio.MAIN_BRANCH}...{ticket['branch']}"
    exclude = f":(exclude){DIFF_IGNORED}"
    stat = gitio.git(project, "-c", "core.quotepath=false", "diff", "--stat", spec, "--",
                     ".", exclude, check=False).stdout.strip()
    if not stat:
        return ""
    patch = gitio.git(project, "-c", "core.quotepath=false", "diff", spec, "--", ".",
                      exclude, check=False).stdout
    if len(patch) > limit:
        patch = patch[:limit] + ("\n[... the rest of the diff is cut; `git diff "
                                 f"{gitio.MAIN_BRANCH}...HEAD` shows it ...]\n")
    return f"\nThe change on the branch so far:\n{stat}\n\n{patch}"


# --- ① classification -----------------------------------------------------------

def classify(project: Path | str, ticket_id: int) -> Ticket:
    """① intake: the chief reads the owner's words and names the work (7.6)."""
    project = Path(project)
    cfg = config.load_hub_config()
    with locking.project_lock(registry.get_project(project)["name"]):
        ticket = tickets.load(project, ticket_id)
        value, result = _ask(
            project, ticket_id, "chief",
            _context(project, ticket) + "\nClassify this ticket.",
            cfg=cfg, ruleset=constitution.resolve(project))
        ticket = tickets.load(project, ticket_id)
        title = flatten(value["title"])[:tickets.TITLE_MAX] or ticket["title"]
        ticket.update({"kind": value["kind"], "title": title, "named_by": "chief",
                       "chief_session": result.session_id or ticket.get("chief_session")})
        return tickets.write(project, ticket, f"ticket {ticket_id:04d}: classified",
                             note=f"classified by the chief as {value['kind']}: "
                                  f"{value['summary']}")


# --- the loop ---------------------------------------------------------------------

def run(project: Path | str, ticket_id: int, *, lane: str | None = None,
        say: Say = print) -> Ticket:
    """Advance until a checkpoint, an unmerged branch, a block, or close."""
    project = Path(project)
    cfg = config.load_hub_config()
    with locking.project_lock(registry.get_project(project)["name"]):
        while True:
            ticket = tickets.load(project, ticket_id)
            if ticket.get("blocked") or ticket["stage"] == "close":
                return ticket
            try:
                verdict = spend.budget(ticket, cfg)
                if verdict == "stop":
                    raise Blocked(_budget_reason(ticket, cfg))
                if verdict == "warn":
                    say(f"  Spend so far: {ticket['spend']['weighted_tokens']} weighted "
                        f"tokens, past the warning line.")
                stop = _step(project, ticket, lane, cfg, say)
                after = tickets.load(project, ticket_id)
                # A fix round keeps the stage and counts a round: that is progress.
                if not stop and after["stage"] == ticket["stage"] and not after.get("blocked") \
                        and after.get("fix_rounds") == ticket.get("fix_rounds"):
                    # A handler that neither waits nor moves the ticket would spin
                    # for ever; found by mutating the review stop.
                    raise Blocked(f"no progress at {tickets._label(ticket['stage'])}: the "
                                  f"stage finished without moving the ticket on")
            except Blocked as exc:
                say(f"  Stopped: {exc}")
                return tickets.block(project, ticket_id, str(exc))
            if stop:
                return tickets.load(project, ticket_id)


def _step(project: Path, ticket: Ticket, lane: str | None, cfg: Mapping[str, Any],
          say: Say) -> bool:
    """Do one stage's work. True when the ticket must now wait for the owner."""
    stage, ticket_id = ticket["stage"], ticket["id"]
    say(f"{tickets._label(stage)}")

    checkpoint = tickets.CHECKPOINT_AT.get(stage)
    if checkpoint and ticket["checkpoints"][checkpoint] == "approved":
        # Approved already - typically at ⑨, where approve could not move on
        # because the branch was not merged yet. Try again rather than ask again.
        try:
            tickets.advance(project, ticket_id)
        except ConfigError as exc:
            say(f"  Waiting: {exc}")
            return True
        return False

    if stage == "intake":
        # Only when nobody has named the work yet: the owner's own kind and title
        # (--kind, the fallback questions, --from-queue) are never overwritten.
        if ticket.get("named_by") is None:
            classify(project, ticket_id)
        tickets.advance(project, ticket_id)
        return False

    if stage == "triage":
        generated.refresh(project)                          # §4.6: ② refreshes the snapshot
        ruleset = constitution.resolve(project)
        facts, _ = _ask(project, ticket_id, "explorer",
                        _context(project, ticket) + "\nFind where this change would land.",
                        cfg=cfg, ruleset=ruleset, cwd=_main_view(project))
        chosen, reason = decide_lane(facts, ruleset)
        if lane is not None:
            hit = _security_hit(list(facts.get("files") or []), ruleset)
            if lane == "fast" and hit:
                raise ConfigError(f"The fast lane is refused: {hit[0]} matches the "
                                  f"security-sensitive glob {hit[1]} (spec 8.2).")
            chosen, reason = lane, "chosen by the owner"
        if ticket.get("lane") == "full" and chosen == "fast":
            chosen, reason = "full", "it was already full, and a lane is never demoted"
        tickets.advance(project, ticket_id, lane=chosen,
                        note=f"explorer: {', '.join(facts['files']) or 'no files'}; "
                             f"{chosen} because {reason}",
                        fields={"templates": dict(facts.get("templates") or {})})
        return False

    ruleset = constitution.resolve(project)
    if stage == "design":
        tree = _worktree(project, ticket_id)
        ticket = tickets.load(project, ticket_id)
        previous = tickets.on_branch(project, ticket, "plan.md")
        rejected = ticket["checkpoints"]["design"] == "rejected"
        if previous is None or rejected:
            ask_for = "Write the plan."
            if rejected:
                ask_for = ("The owner rejected the previous plan - the reason is in the "
                           "history above. Write a new plan that answers it.\n\n"
                           f"The rejected plan:\n{previous}")
            plan, _ = _ask(project, ticket_id, "architect",
                           _context(project, ticket) + _change(project, ticket)
                           + "\n" + ask_for,
                           cfg=cfg, ruleset=ruleset, cwd=tree)
            _commit_ticket_file(tree, ticket, "plan.md", plan["plan_md"],
                                f"docs(plan): ticket {ticket_id:04d}")
            ticket = tickets.load(project, ticket_id)
            ticket["checkpoints"]["design"] = "pending"
            tickets.write(project, ticket, f"ticket {ticket_id:04d}: plan written",
                          note=("③ plan rewritten after the rejection" if rejected
                                else "③ plan written") + "; waiting for your approval")
        say(f"  Waiting for you: `taller ticket show {ticket_id}`, then approve or reject.")
        return True

    if stage == "build":
        tree = _worktree(project, ticket_id)
        ticket = tickets.load(project, ticket_id)
        plan = tickets.on_branch(project, ticket, "plan.md") or ""
        built, _ = _ask(project, ticket_id, "implementer",
                        _context(project, ticket) + (f"\nThe approved plan:\n{plan}" if plan
                                                     else "") + "\nMake the change.",
                        cfg=cfg, ruleset=ruleset, cwd=tree, writable=[str(tree)])
        if gitio.git(tree, "status", "--porcelain", check=False).stdout.strip():
            gitio.git(tree, "add", "--all")
            gitio.git(tree, "commit", "--quiet", "-m",
                      "chore: uncommitted work from the implementer")
        ticket = tickets.load(project, ticket_id)
        diff = _diff(project, ticket["branch"])
        if not diff["files"]:
            raise Blocked("the implementer finished without changing anything on the branch")
        reason = needs_promotion(diff, ticket, ruleset)
        if reason:
            ticket.update({"lane": "full", "stage": "design"})
            ticket["checkpoints"]["design"] = "pending"
            ticket["checkpoints"]["staging"] = "pending"
            tickets.write(project, ticket, f"ticket {ticket_id:04d}: promoted to full",
                          note=f"promoted to full at ④ build: {reason}. The code written "
                               f"so far is kept and goes to the architect.")
            say(f"  Promoted to the full lane: {reason}.")
            return False
        tickets.advance(project, ticket_id, note=f"implementer: {built['summary']}")
        return False

    if stage == "gates":
        return _gates(project, ticket_id, cfg, ruleset, say)

    if stage == "smoke":
        return _smoke(project, ticket_id, cfg, ruleset, say)

    if stage == "review":
        tree = _worktree(project, ticket_id)
        ticket = tickets.load(project, ticket_id)
        if tickets.on_branch(project, ticket, "review.md") is None:
            summary, _ = _ask(project, ticket_id, "summariser",
                              _context(project, ticket) + _change(project, ticket)
                              + _gate_report(project, ticket, ruleset)
                              + "\nSummarise the change for review.",
                              cfg=cfg, ruleset=ruleset, cwd=tree)
            _commit_ticket_file(tree, ticket, "review.md",
                                summary["summary_md"].rstrip() + "\n"
                                + _findings_section(project, ticket),
                                f"docs(review): ticket {ticket_id:04d}")
            tickets.write(project, tickets.load(project, ticket_id),
                          f"ticket {ticket_id:04d}: review written",
                          note="⑦ summary written; waiting for your review")
        say(f"  Waiting for you: `taller ticket show {ticket_id}`, then approve or reject.")
        return True

    if stage == "pr":
        ticket = _pull_request(project, ticket_id, say)
        try:
            tickets.advance(project, ticket_id, note=_MERGE_NOTE)
        except ConfigError as exc:
            say(f"  Waiting for the merge: {exc}")
            return True
        return False

    if stage == "merge":
        tickets.advance(project, ticket_id)
        return False

    if stage == "staging":
        # Spec 13.1: bringing staging up is hers to run, on the host that has
        # Docker and can reach the private network. Taller names the command.
        say(f"  Bring it up with `taller stage {ticket_id}`, look at it, then "
            f"`taller ticket approve {ticket_id}`.")
        return True

    # release: an owner checkpoint with nothing to do first.
    say(f"  Waiting for you: `taller ticket approve {ticket_id}`.")
    return True


# --- ⑤ gates and ⑥ smoke (spec 9) ---------------------------------------------------

def _gates(project: Path, ticket_id: int, cfg: Mapping[str, Any],
           ruleset: Mapping[str, Any], say: Say, *, commands_ran: bool = False) -> bool:
    """Select, run, record, route. A command finding re-runs the gates once."""
    tree = _worktree(project, ticket_id)
    ticket = tickets.load(project, ticket_id)
    change = gate_diff.build(project, gitio.MAIN_BRANCH, ticket["branch"])
    selected = gates.select(ticket, change, ruleset, has_tests=_has_tests(change, ruleset))
    say(f"  Gates: {', '.join(selected)}")
    snapshot = _main_snapshot_sha(project)
    results: list[inference.Result] = []
    diff_text = _gate_patch(project, ticket)
    runners: dict[str, Callable[[], dict[str, Any]]] = {
        "constitution": lambda: constitution_gate.run(change, ruleset, snapshot_sha=snapshot),
        "size": lambda: size_gate.run(change, ruleset, tree=gate_diff.tree(tree)),
        "tests": lambda: tests_gate.run(tree, ruleset, project=project),
    }
    for name in llm.GATES:
        runners[name] = (lambda name=name: llm.run(
            name, project, ticket, diff_text, ruleset, cfg, cwd=tree,
            on_result=results.append)[0])
    workers = max(1, int((cfg.get("concurrency") or {}).get("max_parallel_gates") or 1))
    clean = _dirty(tree)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {name: pool.submit(_safely, name, runners[name]) for name in selected}
    verdicts = [futures[name].result() for name in selected]
    _restore(tree, _dirty(tree) - clean)     # a gate leaves nothing for a fixer to sweep
    for result in results:                  # folded here, one writer at a time
        if result.usage or result.ok:
            spend.fold(project, ticket_id, result, cfg)
    _known_failures(project, verdicts, ruleset)
    findings = _record(project, ticket_id, tree, verdicts, ruleset, "⑤ gates")
    return _route(project, ticket_id, findings, cfg, ruleset, say, stage="gates",
                  commands_ran=commands_ran)


def _smoke(project: Path, ticket_id: int, cfg: Mapping[str, Any],
           ruleset: Mapping[str, Any], say: Say) -> bool:
    tree = _worktree(project, ticket_id)
    ticket = tickets.load(project, ticket_id)
    changed = [f["path"] for f in
               gate_diff.build(project, gitio.MAIN_BRANCH, ticket["branch"])["files"]]
    verdict = _safely("smoke", lambda: smoke_gate.run(
        tree, ruleset, templates=ticket.get("templates") or {}, changed=changed,
        project=project))
    findings = _record(project, ticket_id, tree, [verdict], ruleset, "⑥ smoke")
    return _route(project, ticket_id, findings, cfg, ruleset, say, stage="smoke")


def _safely(name: str, runner: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """A gate that crashed could not run: `result: error`, never a pass (7.4)."""
    try:
        return runner()
    except Exception as exc:                 # the crash itself is the finding
        return {"gate": name, "result": "error", "findings": [], "metrics": {},
                "error": f"{type(exc).__name__}: {exc}"}


def _record(project: Path, ticket_id: int, tree: Path, verdicts: list[dict[str, Any]],
            ruleset: Mapping[str, Any], label: str) -> list[dict[str, Any]]:
    """Overrides applied; `gates/<name>.md` committed on the branch; status updated."""
    hub_sha = str(ruleset.get("hub_sha") or "")
    findings: list[dict[str, Any]] = []
    for verdict in verdicts:
        own = verdict["findings"]
        # apply() appends findings about the overrides themselves; the
        # constitution gate already reports those, once.
        verdict["findings"] = overrides.apply(own, dict(ruleset))[:len(own)]
        if verdict["result"] != "error":
            verdict["result"] = gates.verdict(verdict["gate"], verdict["findings"],
                                              verdict["metrics"])["result"]
        findings.extend(verdict["findings"])
    findings.extend(gates.errors(verdicts))

    ticket = tickets.load(project, ticket_id)
    folder = tree / tickets.ticket_dir(ticket) / "gates"
    folder.mkdir(parents=True, exist_ok=True)
    for verdict in verdicts:
        (folder / f"{verdict['gate']}.md").write_bytes(
            gates.render_verdict(verdict, hub_sha=hub_sha, prose=_prose(verdict)))
    relative = folder.relative_to(tree).as_posix()
    gitio.git(tree, "add", "--", relative)
    if gitio.git(tree, "diff", "--cached", "--quiet", check=False).returncode:
        gitio.git(tree, "commit", "--quiet", "-m",
                  f"chore(gates): ticket {ticket_id:04d} verdicts", "--", relative)

    ticket["gates"] = list(dict.fromkeys([*(ticket.get("gates") or []),
                                          *(v["gate"] for v in verdicts)]))
    ticket.setdefault("verdicts", {})
    for verdict in verdicts:
        ticket["verdicts"][verdict["gate"]] = {"result": verdict["result"],
                                               **gates.counts(verdict["findings"]),
                                               "hub_sha": hub_sha}
    tickets.write(project, ticket, f"ticket {ticket_id:04d}: {label.split()[-1]} ran",
                  note=f"{label}: " + ", ".join(f"{v['gate']} {v['result']}"
                                                for v in verdicts))
    return findings


def _prose(verdict: Mapping[str, Any]) -> str:
    if verdict["result"] == "error":
        return f"The {verdict['gate']} gate could not run.\n\n{verdict.get('error', '')}"
    if not verdict["findings"]:
        return f"The {verdict['gate']} gate found nothing."
    return "\n".join(f"- {_describe(f)}" for f in verdict["findings"])


def _describe(found: Mapping[str, Any]) -> str:
    where = f" at {found['file']}:{found['line']}" if found.get("file") else ""
    hint = f" ({found['fix_hint']})" if found.get("fix_hint") else ""
    return f"{found['rule']} ({found['severity']}){where}: {found['message']}{hint}"


def _route(project: Path, ticket_id: int, findings: list[dict[str, Any]],
           cfg: Mapping[str, Any], ruleset: Mapping[str, Any], say: Say, *,
           stage: str, commands_ran: bool = False) -> bool:
    """Spec 9.3 and 9.7: command, then the owner, then a fixer - or move on."""
    routed = gates.route(findings)
    if routed["command"]:
        described = "; ".join(_describe(f) for f in routed["command"])
        if commands_ran or stage != "gates":
            raise Blocked(f"a deterministic fix ran and the finding remains: {described}")
        for found in routed["command"]:
            if found["rule"] == "constitution.resolved-snapshot-stale":
                generated.refresh(project)          # `taller resolve`
        say("  Ran `taller resolve` for a stale snapshot; running the gates again.")
        return _gates(project, ticket_id, cfg, ruleset, say, commands_ran=True)
    if routed["escalate"]:
        raise Blocked("the gates found what needs your decision: "
                      + "; ".join(_describe(f) for f in routed["escalate"]))
    if routed["agent"]:
        limit = int((ruleset.get("thresholds") or {}).get("max_fix_rounds", 2))
        rounds = int(tickets.load(project, ticket_id).get("fix_rounds") or 0)
        if rounds >= limit:
            raise Blocked(f"{len(routed['agent'])} finding(s) survived {limit} fix rounds: "
                          + "; ".join(_describe(f) for f in routed["agent"]))
        _fix_round(project, ticket_id, routed["agent"], cfg, ruleset, say,
                   back_to_gates=stage != "gates")
        return False
    medium = len(routed["summary"])
    tickets.advance(project, ticket_id,
                    note=f"{medium} MEDIUM finding(s) go to your review" if medium else None)
    return False


def _fix_round(project: Path, ticket_id: int, found: list[dict[str, Any]],
               cfg: Mapping[str, Any], ruleset: Mapping[str, Any], say: Say, *,
               back_to_gates: bool) -> None:
    """One fixer round (spec 9.7): never a test file - enforced, then verified."""
    tree = _worktree(project, ticket_id)
    ticket = tickets.load(project, ticket_id)
    before = gitio.git(tree, "rev-parse", "HEAD").stdout.strip()
    # What is already dirty - a gate's coverage.xml, the owner's own edit - is not
    # the fixer's to commit, and not the fixer's to be blamed for.
    baseline = _dirty(tree)
    listing = "\n".join(f"- {_describe(f)}" for f in found)
    fixed, _ = _ask(project, ticket_id, "fixer",
                    _context(project, ticket) + _change(project, ticket)
                    + f"\nFix these findings, and nothing else:\n{listing}\n",
                    cfg=cfg, ruleset=ruleset, cwd=tree, writable=[str(tree)])
    leftovers = sorted(_dirty(tree) - baseline)
    if leftovers:
        gitio.git(tree, "add", "--", *leftovers)
        gitio.git(tree, "commit", "--quiet", "-m", "chore: uncommitted work from the fixer",
                  "--", *leftovers)
    touched = _paths_between(tree, before, "HEAD")
    tests_dir = str((ruleset.get("paths") or {}).get("tests_dir") or "tests").strip("/")
    changed_tests = [path for path in touched
                     if globs.match(path, f"{tests_dir}/**")
                     or any(globs.match(path, pattern) for pattern in TEST_FILES + TEST_CONFIG)]
    if changed_tests:
        # --keep leaves what was dirty before the round alone; --hard only if it must.
        if gitio.git(tree, "reset", "--quiet", "--keep", before, check=False).returncode:
            gitio.git(tree, "reset", "--quiet", "--hard", before)
        raise Blocked(f"the fixer changed {', '.join(changed_tests)} - a test is changed by "
                      f"a person, never to make a check pass - so its round was undone. "
                      f"The findings need you: " + "; ".join(_describe(f) for f in found))
    ticket = tickets.load(project, ticket_id)
    ticket["fix_rounds"] = int(ticket.get("fix_rounds") or 0) + 1
    if back_to_gates:
        ticket["stage"] = "gates"            # changed code is gated again before smoke
    tickets.write(project, ticket, f"ticket {ticket_id:04d}: fix round {ticket['fix_rounds']}",
                  note=f"fix round {ticket['fix_rounds']}: {fixed['summary']}")
    say(f"  Fix round {ticket['fix_rounds']}: {fixed['summary']}")


def _pull_request(project: Path, ticket_id: int, say: Say) -> Ticket:
    """⑧: the branch becomes a pull request carrying its own evidence (spec 13).

    Created once - a ticket that waits here for a merge passes through this stage
    on every run. A project with no GitHub remote is not an error: she merges it
    herself, which is what phases A to C have always done.
    """
    ticket = tickets.load(project, ticket_id)
    if ticket.get("pr"):
        say(f"  Pull request #{ticket['pr']} is open; waiting for it to be merged.")
        return ticket
    number, reason = prs.create(project, ticket)
    if number:
        ticket["pr"] = number
        return tickets.write(project, ticket, f"ticket {ticket_id:04d}: pull request opened",
                             note=f"⑧ pull request #{number} opened")
    if reason:
        say(f"  The pull request could not be opened ({reason}). The branch "
            f"{ticket['branch']} is ready; merge it yourself and run this again.")
        return tickets.write(project, ticket, f"ticket {ticket_id:04d}: no pull request",
                             note=f"⑧ pull request not opened: {reason}")
    say(f"  This project has no GitHub remote, so there is no pull request to open. "
        f"Merge {ticket['branch']} into {gitio.MAIN_BRANCH} yourself, then run this again.")
    return ticket


def _dirty(tree: Path) -> set[str]:
    """Every path `git status` reports, verbatim (no quoting), renames as two."""
    raw = gitio.git(tree, "-c", "core.quotepath=false", "status", "--porcelain", "-z",
                    "--untracked-files=all", "--no-renames", check=False).stdout
    return {entry[3:] for entry in raw.split("\0") if len(entry) > 3}


def _restore(tree: Path, paths: set[str]) -> None:
    """Undo what the gates wrote - a rewritten coverage.xml, an htmlcov/ - so it can
    ride no commit to `main`."""
    for path in sorted(paths):
        tracked = gitio.git(tree, "ls-files", "--error-unmatch", "--", path,
                            check=False).returncode == 0
        if tracked:
            gitio.git(tree, "checkout", "--quiet", "--", path, check=False)
        else:
            (tree / path).unlink(missing_ok=True)


def _paths_between(tree: Path, before: str, after: str) -> list[str]:
    """Every path changed between two commits, verbatim: an accented or spaced test
    file must not slip past the check because git quoted or split its name."""
    raw = gitio.git(tree, "-c", "core.quotepath=false", "diff", "--name-only", "-z",
                    "--no-renames", f"{before}..{after}").stdout
    return [path for path in raw.split("\0") if path]


def _known_failures(project: Path, verdicts: list[dict[str, Any]],
                    ruleset: Mapping[str, Any]) -> None:
    """A test failing on `main` too is not the change's to fix (§9.3 in spirit):
    it goes to the owner's summary, not to a fixer who would edit unrelated code."""
    for verdict in verdicts:
        if verdict.get("gate") != "tests" or verdict.get("result") == "error":
            continue
        failed = [f for f in verdict["findings"] if f["rule"] == "tests.failed"
                  and f.get("test_id")]
        if not failed:
            continue
        known = tests_gate.failing(_main_view(project), [f["test_id"] for f in failed],
                                   ruleset, project=project)
        for found in failed:
            if found["test_id"] in known:
                found["severity"] = "MEDIUM"
                found["message"] += " It fails on main too: already failing on main."


def _findings_section(project: Path, ticket: Mapping[str, Any]) -> str:
    """What the gates found, written by Taller - not left to the summariser's prose."""
    lines: list[str] = []
    for name in ticket.get("gates") or []:
        text = tickets.on_branch(project, ticket, f"gates/{name}.md")
        if not text:
            continue
        lines.extend(f"- {_describe(f)}" for f in gates.parse_verdict(text)["findings"]
                     if f.get("severity") in ("BLOCKER", "HIGH", "MEDIUM"))
    if not lines:
        return "\n## What the gates found\n\nNothing for you to look at.\n"
    return "\n## What the gates found\n\n" + "\n".join(lines) + "\n"


def _gate_patch(project: Path, ticket: Mapping[str, Any]) -> str:
    """The change as the model gates see it: whole, up to GATE_PATCH_MAX."""
    return _change(project, ticket, limit=GATE_PATCH_MAX)


def _has_tests(change: Mapping[str, Any], ruleset: Mapping[str, Any]) -> bool:
    """§9.2's "tests exist": any tracked test file, by the fixer's own patterns."""
    return any(globs.match(path, pattern) for path in change.get("tracked") or []
               for pattern in TEST_FILES)


def _main_snapshot_sha(project: Path) -> str | None:
    """The hub commit `main`'s snapshot was resolved from (spec 4.6)."""
    raw = tickets.read_main(project, SNAPSHOT)
    try:
        return json.loads(raw.decode("utf-8")).get("hub_sha") if raw else None
    except (ValueError, AttributeError):
        return None


def _gate_report(project: Path, ticket: Mapping[str, Any],
                 ruleset: Mapping[str, Any]) -> str:
    """For ⑦: every verdict's counts, every MEDIUM finding, and whether the rules
    moved under the ticket since the gates ran (spec 14)."""
    verdicts = ticket.get("verdicts") or {}
    if not verdicts:
        return ""
    lines = ["\nThe gates:"]
    mediums: list[str] = []
    for name in ticket.get("gates") or verdicts:
        verdict = verdicts.get(name) or {}
        counts = ", ".join(f"{verdict.get(k, 0)} {k}" for k in
                           ("blocker", "high", "medium", "low", "nit") if verdict.get(k))
        lines.append(f"- {name}: {verdict.get('result', '?')}"
                     + (f" ({counts})" if counts else ""))
        text = tickets.on_branch(project, ticket, f"gates/{name}.md")
        if text:
            mediums.extend(_describe(f) for f in gates.parse_verdict(text)["findings"]
                           if f.get("severity") == "MEDIUM")
    if mediums:
        lines.append("\nMEDIUM findings for the owner to see (never auto-fixed):")
        lines.extend(f"- {line}" for line in mediums)
    ran = sorted({str(v.get("hub_sha")) for v in verdicts.values() if v.get("hub_sha")})
    now = str(ruleset.get("hub_sha") or "")
    moved = [sha for sha in ran if sha != now]
    if moved and now:
        lines.append(f"\nNote: the rules changed since the gates ran (hub "
                     f"{', '.join(sha[:7] for sha in moved)} then, {now[:7]} now). Say so "
                     f"in the summary: the verdicts were reached under the older rules.")
    return "\n".join(lines) + "\n"


# --- files on the branch ----------------------------------------------------------

def _main_view(project: Path) -> Path:
    """The `main` worktree, brought to `main`'s tip, for a read-only role to look at."""
    tree = gitio.ensure_main_worktree(project)
    gitio.git(tree, "checkout", "--quiet", "--detach", "--force", gitio.MAIN_BRANCH)
    return tree


def _worktree(project: Path, ticket_id: int) -> Path:
    """The ticket's worktree, opened (from ③ on the full lane) or reopened if gone."""
    ticket = tickets.load(project, ticket_id)
    tree = tickets._worktree(project, ticket)
    if ticket.get("branch") and tree.is_dir():
        return tree
    tickets._open_worktree(project, ticket)
    tickets.write(project, ticket, f"ticket {ticket_id:04d}: branch {ticket['branch']}",
                  note=f"branch {ticket['branch']} opened")
    return tree





def _commit_ticket_file(tree: Path, ticket: Mapping[str, Any], name: str, text: str,
                        message: str) -> None:
    path = tree / tickets.ticket_dir(ticket) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8", newline="")
    relative = str(path.relative_to(tree)).replace("\\", "/")
    gitio.git(tree, "add", "--", relative)
    gitio.git(tree, "commit", "--quiet", "-m", message, "--", relative)
