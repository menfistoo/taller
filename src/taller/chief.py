"""The chief: one ticket, carried from where it is to the next point that needs the owner.

Spec 3.1, 7.6, 8. `run` owns the loop and holds the project lock for all of it,
so the CLI, a second terminal and the cockpit cannot drive one ticket at once
(7.6). Everything the spec states as a rule is decided here in Python - the lane
(8.2), promotion at ④, the budget (7.5), the fallback (14) - and inference is
used only where judgement is: classifying the owner's words, surveying the
code, planning, building, summarising. Every dispatch's usage is folded into
the ticket as soon as it returns.

Phase B has no gates, smoke check, pull request or staging deploy yet (C and F);
those stages pass through with a note, and every owner checkpoint still holds.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from . import (config, constitution, generated, gitio, inference, locking, models, registry,
               roles, spend, tickets)
from .errors import ConfigError, TallerError

Ticket = dict[str, Any]
Say = Callable[[str], None]

PASS_THROUGH = {
    "gates": "the quality gates arrive in phase C; passed through",
    "smoke": "the smoke check arrives in phase C; passed through",
    "pr": "the pull request arrives in phase F; merge the branch yourself",
}
# How the CLI says a model is out of reach, as distinct from any other failure.
UNAVAILABLE = re.compile(r"model\b.*\b(not available|not found|does not exist|unavailable|"
                         r"invalid)", re.IGNORECASE)
DIFF_IGNORED = ".taller/work/"


class Blocked(TallerError):
    """A stage cannot go on without the owner; the reason goes on the ticket."""


# --- lanes (8.2) ------------------------------------------------------------------

def _security_hit(paths: list[str], ruleset: Mapping[str, Any]) -> tuple[str, str] | None:
    globs = ((ruleset.get("paths") or {}).get("security_sensitive")) or []
    for path in paths:
        for glob in globs:
            if fnmatch.fnmatch(path.replace("\\", "/"), glob):
                return path, glob
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


def _context(project: Path, ticket: Mapping[str, Any]) -> str:
    words = tickets._words(project, ticket).strip()
    return f"Ticket {ticket['id']:04d}: {ticket['title']}\n\nThe owner's words:\n{words}\n"


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
        ticket.update({"kind": value["kind"], "title": value["title"][:tickets.TITLE_MAX],
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
                if not stop and tickets.load(project, ticket_id)["stage"] == ticket["stage"] \
                        and not tickets.load(project, ticket_id).get("blocked"):
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

    if stage == "intake":
        if not ticket.get("chief_session"):
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
        tickets.advance(project, ticket_id, lane=chosen,
                        note=f"explorer: {', '.join(facts['files']) or 'no files'}; "
                             f"{chosen} because {reason}")
        return False

    ruleset = constitution.resolve(project)
    if stage == "design":
        tree = _worktree(project, ticket_id)
        ticket = tickets.load(project, ticket_id)
        if _on_branch(project, ticket, "plan.md") is None:
            plan, _ = _ask(project, ticket_id, "architect",
                           _context(project, ticket) + "\nWrite the plan.",
                           cfg=cfg, ruleset=ruleset, cwd=tree)
            _commit_ticket_file(tree, ticket, "plan.md", plan["plan_md"],
                                f"docs(plan): ticket {ticket_id:04d}")
            tickets.write(project, tickets.load(project, ticket_id),
                          f"ticket {ticket_id:04d}: plan written",
                          note="③ plan written; waiting for your approval")
        say(f"  Waiting for you: `taller ticket show {ticket_id}`, then approve or reject.")
        return True

    if stage == "build":
        tree = _worktree(project, ticket_id)
        ticket = tickets.load(project, ticket_id)
        plan = _on_branch(project, ticket, "plan.md") or ""
        built, _ = _ask(project, ticket_id, "implementer",
                        _context(project, ticket) + (f"\nThe approved plan:\n{plan}" if plan
                                                     else "") + "\nMake the change.",
                        cfg=cfg, ruleset=ruleset, cwd=tree, writable=[str(tree)])
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

    if stage in ("gates", "smoke"):
        tickets.advance(project, ticket_id, note=PASS_THROUGH[stage])
        return False

    if stage == "review":
        tree = _worktree(project, ticket_id)
        ticket = tickets.load(project, ticket_id)
        if _on_branch(project, ticket, "review.md") is None:
            summary, _ = _ask(project, ticket_id, "summariser",
                              _context(project, ticket) + "\nSummarise the change for review.",
                              cfg=cfg, ruleset=ruleset, cwd=tree)
            _commit_ticket_file(tree, ticket, "review.md", summary["summary_md"],
                                f"docs(review): ticket {ticket_id:04d}")
            tickets.write(project, tickets.load(project, ticket_id),
                          f"ticket {ticket_id:04d}: review written",
                          note="⑦ summary written; waiting for your review")
        say(f"  Waiting for you: `taller ticket show {ticket_id}`, then approve or reject.")
        return True

    if stage == "pr":
        try:
            tickets.advance(project, ticket_id, note=PASS_THROUGH["pr"])
        except ConfigError as exc:
            say(f"  Waiting for the merge: {exc}")
            return True
        return False

    if stage == "merge":
        tickets.advance(project, ticket_id)
        return False

    # staging and release: owner checkpoints with nothing to do first.
    say(f"  Waiting for you: `taller ticket approve {ticket_id}`.")
    return True


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


def _on_branch(project: Path, ticket: Mapping[str, Any], name: str) -> str | None:
    if not ticket.get("branch"):
        return None
    raw = gitio.git(project, "cat-file", "blob",
                    f"{ticket['branch']}:{tickets.ticket_dir(ticket)}/{name}", check=False)
    return raw.stdout if raw.returncode == 0 else None


def _commit_ticket_file(tree: Path, ticket: Mapping[str, Any], name: str, text: str,
                        message: str) -> None:
    path = tree / tickets.ticket_dir(ticket) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8", newline="")
    gitio.git(tree, "add", "--", str(path.relative_to(tree)).replace("\\", "/"))
    gitio.git(tree, "commit", "--quiet", "-m", message)
