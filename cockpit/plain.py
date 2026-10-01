"""The machine's state, in her words. Pure: reads the library, imports no Flask.

Everything the plain front shows comes through here, and every word it uses
comes from `words.py`. The twelve stages, the checkpoints, the gates and their
findings all still exist - the work needs them - but what leaves this module is
four states, a sentence about what is happening, and findings as sentences.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from taller import issues, locking, publishing, tickets
from taller.errors import LockTimeout, NotOnMain, TallerError, UncommittedWork

from . import reading, words

# Findings she is asked to look at before saying yes. The rest are small things;
# a finding an override turned into a NIT is a deviation she already allowed.
LOOK = frozenset({"BLOCKER", "HIGH"})
SMALL = frozenset({"MEDIUM", "LOW"})
FILES_SHOWN = 8
REVIEW_FINDINGS = "\n## What the gates found"
# Finished things pile up for as long as a project lives; the front page is for
# what is going on, so it shows the most recent few and counts the rest.
DONE_SHOWN = 5


# The stages where the work writes something for her before it waits: until that
# paper exists, the checkpoint's `pending` only means "not decided yet".
PAPER = {"design": "plan.md", "review": "review.md"}


def state_of(ticket: Mapping[str, Any], *, waiting_to_publish: bool = False,
             ready: bool = True, live: bool = True) -> str:
    """`working`, `needs_you`, `stopped` or `done`.

    Every checkpoint starts `pending` when the ticket is created, so `pending` alone
    does not mean it is waiting for her: at ③ and ⑦ it is still writing the plan
    or the write-up until `ready` - that paper exists on the branch.

    `working` only while something is: without a `live` run, a thing between
    stages was interrupted, and at the pull request it waits on a merge.
    """
    if ticket.get("blocked"):
        return "stopped"
    if ticket.get("stage") == "close" or ticket.get("outcome"):
        return "done"
    checkpoint = tickets.CHECKPOINT_AT.get(ticket.get("stage", ""))
    if checkpoint and (ticket.get("checkpoints") or {}).get(checkpoint) == "pending" and ready:
        return "needs_you"
    if waiting_to_publish:
        return "needs_you"
    if live:
        return "working"
    return "needs_you" if ticket.get("stage") == "pr" else "stopped"


def live(project_name: str, ticket: Mapping[str, Any]) -> bool:
    """Is something working on it now: a run this server started, or any process
    holding the ticket - a run from the terminal, or from before a restart."""
    from . import runs

    ticket_id = int(ticket["id"])
    return locking.driven(project_name, ticket_id) \
        or runs.progress(runs.run_id(project_name, ticket_id))["running"]


def _state(project_name: str, ticket: Mapping[str, Any], *, waiting_to_publish: bool,
           ready: bool) -> tuple[str, bool]:
    """The state, asking whether anything is running only when it matters."""
    state = state_of(ticket, waiting_to_publish=waiting_to_publish, ready=ready)
    if state != "working":
        return state, False
    running = live(project_name, ticket)
    return state_of(ticket, waiting_to_publish=waiting_to_publish, ready=ready,
                    live=running), running


def problem(exc: TallerError) -> str:
    """What a refusal from the library says on her page."""
    if isinstance(exc, LockTimeout):
        return words.BUSY
    if isinstance(exc, UncommittedWork):
        return words.HAND_CHANGES
    if isinstance(exc, NotOnMain):
        return words.NOT_ON_MAIN
    return str(exc)


def doing(ticket: Mapping[str, Any], *, waiting_to_publish: bool = False,
          ready: bool = True, live: bool = True) -> str:
    """One sentence: what it is doing, or what it is waiting for her to do."""
    stage = ticket.get("stage", "")
    state = state_of(ticket, waiting_to_publish=waiting_to_publish, ready=ready, live=live)
    if state == "needs_you" and stage == "pr" and not waiting_to_publish:
        return words.WAITING_FOR_GITHUB if ticket.get("pr") else words.FINISHED_HERE
    if ticket.get("blocked") or state == "stopped":
        # Not "starting your app": that reads as if it still is. It was, and stopped.
        doing_then = words.DOING.get(stage, "")
        return f"Stopped while {doing_then[:1].lower()}{doing_then[1:]}"
    if waiting_to_publish:
        return words.READY_TO_PUBLISH
    if state_of(ticket, ready=ready) == "needs_you":
        return words.WAITING.get(stage, words.DOING.get(stage, ""))
    return words.DOING.get(stage, "")


def sentence(finding: Mapping[str, Any], place: Any = None) -> str:
    """A finding as one line - never its rule id - with where it is, if anywhere.

    `place`, when given, turns a file's path into what she calls it; the line number
    is then left out too, because a line number means nothing to her.
    """
    rule = str(finding.get("rule", ""))
    said = words.FINDINGS.get(rule) or _found_by(rule)
    where = str(finding.get("file") or "")
    if where and place is not None:
        said += f" — {place(where)}"
    elif where:
        line = int(finding.get("line") or 0)
        said += f" — in {where}" + (f", line {line}" if line else "")
    return said


def _found_by(rule: str) -> str:
    """A rule with no sentence of its own, said by the check that reported it."""
    if rule.endswith(".error"):
        return words.CHECK_FOUND["error"]
    return words.CHECK_FOUND.get(rule.split(".", 1)[0], words.CHECK_FOUND["other"])


def split(found: list[Mapping[str, Any]], place: Any = None) -> tuple[list[str], list[str]]:
    """(worth a look before you say yes, small things), as sentences."""
    look = [sentence(f, place) for f in found if str(f.get("severity")) in LOOK]
    small = [sentence(f, place) for f in found if str(f.get("severity")) in SMALL]
    return look, small


def paper_ready(path: Path, ticket: Mapping[str, Any]) -> bool:
    """At ③ or ⑦: has it finished writing what she is to read? Elsewhere, yes."""
    name = PAPER.get(ticket.get("stage", ""))
    return name is None or tickets.on_branch(path, ticket, name) is not None


def waiting_to_publish(path: Path, ticket: Mapping[str, Any]) -> bool:
    """At ⑧, with no pull request because publishing is waiting for her."""
    return (ticket.get("stage") == "pr" and not ticket.get("pr")
            and issues.repo_of(path) is not None and not publishing.automatic(path))


def things(project_name: str, path: Path,
           listed: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Everything asked for in one project, newest first, in her words."""
    if listed is None:
        listed, _ = tickets.list_tickets(path)
    out = []
    for ticket in sorted(listed, key=lambda t: int(t["id"]), reverse=True):
        held = waiting_to_publish(path, ticket)
        ready = paper_ready(path, ticket)
        state, running = _state(project_name, ticket, waiting_to_publish=held, ready=ready)
        out.append({
            "project": project_name,
            "id": int(ticket["id"]),
            "title": ticket["title"],
            "state": state,
            "state_words": words.STATES[state],
            "doing": doing(ticket, waiting_to_publish=held, ready=ready,
                           live=running or state != "stopped"),
            "url": f"/thing/{project_name}/{int(ticket['id'])}",
        })
    return out


def home() -> dict[str, Any]:
    """Her projects and what she asked for in each; whatever needs her, first."""
    projects = []
    for entry in reading.project_entries():
        row = {"name": entry["name"], "available": entry["available"],
               "problem": entry["problem"], "things": []}
        row["publish"] = {"remote": False, "count": 0, "line": ""}
        if entry["available"]:
            path = Path(entry["path"])
            listed, _ = tickets.list_tickets(path)          # once, for both below
            row["things"] = things(entry["name"], path, listed)
            row["publish"] = _publish_line(path, listed)
        counts = {state: sum(1 for t in row["things"] if t["state"] == state)
                  for state in words.STATES}
        row["counts"] = counts
        row["count_line"] = " · ".join(words.counted(state, number)
                                       for state, number in counts.items() if number)             or words.HOME["quiet"]
        done = [t for t in row["things"] if t["state"] == "done"]
        row["shown"] = [t for t in row["things"] if t["state"] != "done"] + done[:DONE_SHOWN]
        row["done_more"] = max(0, len(done) - DONE_SHOWN)
        projects.append(row)
    needs_you = [t for p in projects for t in p["things"] if t["state"] in ("needs_you", "stopped")]
    return {"projects": projects, "needs_you": needs_you}


def _publish_line(path: Path, listed: list[dict[str, Any]]) -> dict[str, Any]:
    """Whether anything of this project's is waiting to leave this computer."""
    waiting = publishing.waiting(path, listed)
    if not waiting["remote"]:
        return {"remote": False, "count": 0, "line": words.PUBLISH["alone"]}
    if not waiting["held"]:
        return {"remote": True, "count": 0, "line": ""}
    return {"remote": True, "count": len(waiting["things"]),
            "line": words.waiting_line(len(waiting["things"]))}


def what_it_did(path: Path, ticket: Mapping[str, Any]) -> dict[str, Any]:
    """The summary it wrote, and the files it changed, named for a person."""
    review = tickets.on_branch(path, ticket, "review.md") or ""
    # The review ends with what the checks found, listed by rule id for the record;
    # her page shows those findings as sentences instead, so only the prose is kept.
    summary = review.split(REVIEW_FINDINGS, 1)[0].strip()
    diff = reading._diff(path, dict(ticket)) if ticket.get("branch") else {"files": [], "total": 0}
    files = [{"name": name_of(ticket, f["path"]),
              "added": f["added"], "removed": f["removed"]}
             for f in diff["files"][:FILES_SHOWN]]
    return {"summary": summary, "files": files,
            "more": max(0, int(diff.get("total", 0)) - len(files))}


def name_of(ticket: Mapping[str, Any], relative: str) -> str:
    """What she calls a file: the summariser's words for it, or its own short name."""
    return str((ticket.get("file_names") or {}).get(relative) or _plain_name(relative))


def _plain_name(relative: str) -> str:
    """`loans/ledger.py` -> `ledger`: the file's own name, without folder or ending."""
    stem = relative.rsplit("/", 1)[-1]
    return stem.split(".", 1)[0] or stem


def thing(project_name: str, ticket_id: int) -> dict[str, Any]:
    """One thing she asked for: what she said, what it did, and what it needs from her."""
    entry = reading.entry_for(project_name)
    path = Path(entry["path"])
    ticket = tickets.load(path, ticket_id)
    held = waiting_to_publish(path, ticket)
    ready = paper_ready(path, ticket)
    state, running = _state(entry["name"], ticket, waiting_to_publish=held, ready=ready)
    found = [f for v in reading._verdicts(path, dict(ticket)) for f in v["findings"]]
    look, small = split(found, place=lambda relative: name_of(ticket, relative))
    checkpoint = tickets.CHECKPOINT_AT.get(ticket["stage"])
    return {
        "project": entry["name"],
        "id": int(ticket["id"]),
        "title": ticket["title"],
        "asked": tickets._words(path, ticket).strip(),
        "state": state,
        "state_words": words.STATES[state],
        "doing": doing(ticket, waiting_to_publish=held, ready=ready,
                       live=running or state != "stopped"),
        # At the plan nothing has been done yet: what she decides on is the plan
        # itself, so it is shown in place of "what it did".
        "plan_text": _plan_for_her(path, ticket)
        if ticket["stage"] == "design" and ready else None,
        "full_plan": ticket["stage"] == "design"
        and tickets.on_branch(path, ticket, "plan-summary.md") is not None,
        "did": what_it_did(path, ticket)
        if ticket.get("branch") and ticket["stage"] != "design" else None,
        "look": look,
        "small": small,
        "stopped": (_why_it_stopped(ticket) if ticket.get("blocked")
                    else words.THING["interrupted"]) if state == "stopped" else "",
        "after_publish": _after_publish(path, ticket) if state == "needs_you"
        and ticket["stage"] == "pr" and not held else None,
        "decide": bool(checkpoint) and state == "needs_you" and not held,
        "publish": held,
        "detail_url": f"/ticket/{entry['name']}/{int(ticket['id'])}",
        "has_plan": bool(ticket.get("branch"))
        and tickets.on_branch(path, ticket, "plan.md") is not None,
    }


def _after_publish(path: Path, ticket: Mapping[str, Any]) -> dict[str, str]:
    """At the pull request, after publishing: what happens next, and where."""
    repo = issues.repo_of(path)
    if ticket.get("pr") and repo:
        return {"note": words.THING["merge_on_github"],
                "url": f"https://github.com/{repo}/pull/{int(ticket['pr'])}"}
    if ticket.get("pr"):
        return {"note": words.THING["merge_on_github"], "url": ""}
    return {"note": words.THING["only_here"], "url": ""}


def plan_of(project_name: str, ticket_id: int) -> dict[str, Any]:
    """The plan a thing followed: in her words first, then as written for the builder."""
    entry = reading.entry_for(project_name)
    path = Path(entry["path"])
    ticket = tickets.load(path, ticket_id)
    return {"project": entry["name"], "id": int(ticket["id"]), "title": ticket["title"],
            "summary": reading._paper(path, dict(ticket), "plan-summary.md"),
            "plan": reading._paper(path, dict(ticket), "plan.md")}


def _plan_for_her(path: Path, ticket: Mapping[str, Any]) -> str | None:
    """The plan in her words when it was written; the builder's plan otherwise
    (a plan from before the two versions existed)."""
    return reading._paper(path, dict(ticket), "plan-summary.md") \
        or reading._paper(path, dict(ticket), "plan.md")


def _why_it_stopped(ticket: Mapping[str, Any]) -> str:
    """One sentence about what stopped it - never a check's log.

    A reason naming a finding it knows is said in that finding's words; any other
    reason is summarised, and the full text stays on the detailed page.
    """
    reason = str((ticket.get("blocked") or {}).get("reason") or "")
    if reason.startswith("the budget is spent"):
        return words.BUDGET_STOPPED
    while_doing = words.DOING.get(ticket.get("stage", ""), "").lower()
    for rule, said in words.FINDINGS.items():
        if rule in reason:
            return f"It stopped while {while_doing}: {said[0].lower()}{said[1:]}."
    return f"It stopped while {while_doing}, and needs you to look at what went wrong."
