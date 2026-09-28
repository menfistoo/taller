"""`taller ticket …`: tickets by command, in plain words (spec 3.5, 7, 8).

Until the chief exists (Phase B), the owner answers what the chief will later
decide - the kind at ①, the lane at ② - and moves the ticket along with these
commands. They only collect input and call `tickets`; every rule lives there.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

import yaml

from .. import chief, gitio, locking, registry, tickets
from ..errors import ConfigError, TallerError
from ..onboarding import Question, ask
from ..prompter import Prompter
from . import common

KIND_CHOICES = (
    ("bug", "something is broken"),
    ("feature", "something new"),
    ("refactor", "tidy up existing code"),
    ("question", "a question to answer"),
    ("idea", "an idea for later"),
)
LANE_CHOICES = (
    ("fast", "small and safe: a text, colour or setting in one file"),
    ("full", "anything else"),
)
TITLE_PROPOSAL_MAX = 72
QUEUE = ".taller/queue.yml"


def _project(args: Any) -> Path:
    project = common.project_path(getattr(args, "path", None)).resolve()
    entry = registry.get_project(project)
    if not registry.is_adopted(entry):
        raise ConfigError(f"{entry['name']} is registered but not adopted yet: "
                          f"`taller project adopt {project}` first.")
    return project


def _label(stage: str) -> str:
    return tickets._label(stage)


def next_hint(ticket: dict) -> str:
    """What moves this ticket on, as the command that does it."""
    number = ticket["id"]
    if ticket["stage"] == "close":
        return f"Closed ({ticket.get('outcome') or 'done'})."
    if ticket.get("blocked"):
        return (f"Blocked: {ticket['blocked']['reason']}. When that is dealt with: "
                f"`taller ticket resume {number}`.")
    checkpoint = tickets.CHECKPOINT_AT.get(ticket["stage"])
    if checkpoint and ticket["checkpoints"][checkpoint] != "approved":
        return (f"Waiting for you at the {checkpoint} checkpoint: "
                f"`taller ticket approve {number}` or `taller ticket reject {number}`.")
    if ticket["stage"] == "triage" and not ticket.get("lane"):
        return (f"Choose its lane: `taller ticket transition {number}` "
                f"(it asks whether the change is small and safe).")
    return f"Next: `taller ticket transition {number}`."


# --- new ---------------------------------------------------------------------

def new(args: Any, prompter: Prompter) -> int:
    project = _project(args)
    if getattr(args, "from_queue", False):
        return _from_queue(project, prompter)

    words = " ".join(args.words).strip() if args.words else ""
    while not words:
        lines = prompter.ask_lines(
            "ticket.words",
            "  What should be done? Say it in your own words.\n"
            "     (Press Enter on an empty line when done.)")
        words = "\n".join(lines).strip()
        if not words:
            prompter.say("  A few words are needed.")
    if getattr(args, "kind", None):
        # The owner names the work themselves (phase D's path).
        title = ask(prompter, Question("ticket.title", "title", 0, "A short title for it",
                                       "text"), default=_propose_title(words))
        ticket = tickets.create(project, title=title, words=words, kind=args.kind)
    else:
        # G2: the owner states intent once; the chief names the work (spec 7.6).
        ticket = tickets.create(project, title=_propose_title(words), words=words,
                                kind="idea", named_by=None)
        try:
            ticket = chief.classify(project, ticket["id"])
        except TallerError as exc:
            if not prompter.interactive:
                # Nobody to ask mid-command. The chief classifies an unnamed
                # ticket at ① anyway, so leave it for then; asking would mean a
                # rerun, and a rerun would make a second ticket.
                prompter.say(f"  The chief could not classify it yet ({exc}); it will be "
                             f"classified when it runs.")
                ticket = tickets.load(project, ticket["id"])
                return _created(prompter, ticket)
            prompter.say(f"  The chief could not classify it ({exc}). Answer these two "
                         f"yourself:")
            kind = ask(prompter, Question("ticket.kind", "kind", 0,
                                          "What kind of work is it?", "choice",
                                          choices=KIND_CHOICES))
            title = ask(prompter, Question("ticket.title", "title", 0,
                                           "A short title for it", "text"),
                        default=ticket["title"])
            ticket = tickets.load(project, ticket["id"])
            ticket.update({"kind": kind, "title": title, "named_by": "owner"})
            ticket = tickets.write(project, ticket, f"ticket {ticket['id']:04d}: named",
                                   note=f"named by the owner: {kind}")
    return _created(prompter, ticket)


def _created(prompter: Prompter, ticket: Mapping[str, Any]) -> int:
    lines = [f"Created ticket {ticket['id']:04d} - {ticket['title']}",
             f"  {tickets.ticket_dir(ticket)}"]
    if ticket.get("issue"):
        lines.append(f"  GitHub issue #{ticket['issue']}")
    lines.append(f"  {next_hint(ticket)}")
    prompter.say("\n".join(lines))
    return 0


def _propose_title(words: str) -> str:
    first = re.split(r"[.!?\n]", words.strip(), maxsplit=1)[0].strip()
    return first[:TITLE_PROPOSAL_MAX].rstrip() or words.strip()[:TITLE_PROPOSAL_MAX]


def _from_queue(project: Path, prompter: Prompter) -> int:
    """Answer ⑫ becomes tickets, and the queue empties (spec 11.4).

    An entry whose title is already a ticket is skipped: a run that died half
    way must not duplicate what it already made.
    """
    with locking.project_lock(registry.get_project(project)["name"]):
        proposed = _queued_titles(project)
        if not proposed:
            prompter.say("The queue is empty: nothing to turn into tickets.")
            return 0
        existing = {ticket["title"] for ticket in tickets.list_tickets(project)[0]}
        made = [tickets.create(project, title=title, words=title, kind="feature")
                for title in proposed if title not in existing]
        emptied = ("# The smallest useful version, in the owner's words (onboarding "
                   "answer 12).\n# Turned into tickets by `taller ticket new "
                   "--from-queue`.\nproposed: []\n")
        gitio.commit_to_main(project, {QUEUE: emptied.encode("utf-8")},
                             "taller: the queue became tickets")
    lines = [f"Made {len(made)} tickets from the queue:"]
    lines += [f"  {t['id']:04d}  {t['title']}" for t in made]
    skipped = len(proposed) - len(made)
    if skipped:
        lines.append(f"  ({skipped} already existed and were skipped.)")
    prompter.say("\n".join(lines))
    return 0


def _queued_titles(project: Path) -> list[str]:
    """The titles `queue.yml` proposes. A file the owner broke is a message, not a trace."""
    raw = tickets.read_main(project, QUEUE)
    if not raw:
        return []
    try:
        queue = yaml.safe_load(raw.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{QUEUE} is not valid YAML: {exc}") from exc
    if queue is None:
        return []
    if not isinstance(queue, dict) or not isinstance(queue.get("proposed") or [], list):
        raise ConfigError(f"{QUEUE} must hold `proposed:` followed by a list of "
                          f"`- title: ...` entries.")
    return [str(entry.get("title", "")).strip() for entry in queue.get("proposed") or []
            if isinstance(entry, dict) and str(entry.get("title", "")).strip()]


# --- list and show -----------------------------------------------------------

def list_(args: Any, prompter: Prompter) -> int:
    project = _project(args)
    found, problems = tickets.list_tickets(project)
    shown = [t for t in found if args.all or t["stage"] != "close"]
    if not shown and not problems:
        prompter.say("No open tickets. `taller ticket new` starts one.")
        return 0
    lines = [f"  {t['id']:04d}  {_label(t['stage']):<12} {t.get('lane') or '-':<5} "
             f"{t['title']}" + ("   [blocked]" if t.get("blocked") else "")
             for t in shown]
    lines += [f"  Could not read: {problem}" for problem in problems]
    prompter.say("\n".join(lines))
    return 0


def show(args: Any, prompter: Prompter) -> int:
    project = _project(args)
    ticket = tickets.load(project, args.id)
    marks = {"approved": "approved", "pending": "waiting", "skipped": "skipped",
             "rejected": "rejected"}
    checkpoints = ", ".join(f"{name} {marks.get(state, state)}"
                            for name, state in ticket["checkpoints"].items())
    lines = [f"Ticket {ticket['id']:04d} - {ticket['title']}",
             f"  Kind: {ticket['kind']}.  Stage: {_label(ticket['stage'])}."
             f"  Lane: {ticket.get('lane') or 'not chosen yet'}.",
             f"  Checkpoints: {checkpoints}."]
    if ticket.get("branch"):
        lines.append(f"  Branch: {ticket['branch']}")
    if ticket.get("issue"):
        lines.append(f"  GitHub issue #{ticket['issue']}")
    if tickets.effective_sync(project, ticket) == "pending":
        lines.append("  Not pushed to GitHub yet; the next move retries.")
    lines.append(f"  {next_hint(ticket)}")
    raw = tickets.read_main(project, f"{tickets.ticket_dir(ticket)}/notes.md") or b""
    history = raw.decode("utf-8", errors="replace").strip().splitlines()[-6:]
    if history:
        lines += ["", "  Latest notes:"] + [f"    {line}" for line in history]
    prompter.say("\n".join(lines))
    return 0


# --- moving it ---------------------------------------------------------------

def transition(args: Any, prompter: Prompter) -> int:
    project = _project(args)
    ticket = tickets.load(project, args.id)
    lane = args.lane
    if ticket["stage"] == "triage" and not ticket.get("lane") and lane is None \
            and not ticket.get("blocked"):
        lane = ask(prompter, Question("ticket.lane", "lane", 0,
                                      "How big is this change?", "choice",
                                      choices=LANE_CHOICES))
    return _report(prompter, tickets.advance(project, args.id, lane=lane))


def approve(args: Any, prompter: Prompter) -> int:
    project = _project(args)
    return _report(prompter, tickets.approve(project, args.id), verb="Approved")


def reject(args: Any, prompter: Prompter) -> int:
    project = _project(args)
    reason = (args.reason or "").strip()
    while not reason:
        reason = prompter.ask("ticket.reason",
                              "  Why is it rejected? The next attempt starts from this.").strip()
    return _report(prompter, tickets.reject(project, args.id, reason), verb="Rejected")


def resume(args: Any, prompter: Prompter) -> int:
    project = _project(args)
    ticket, repairs = tickets.resume(project, args.id)
    lines = [f"Ticket {ticket['id']:04d} is at {_label(ticket['stage'])}."]
    lines += [f"  {repair[0].upper()}{repair[1:]}." for repair in repairs] or \
        ["  Nothing needed repairing."]
    lines.append(f"  {next_hint(ticket)}")
    prompter.say("\n".join(lines))
    return 0


def run(args: Any, prompter: Prompter) -> int:
    """`taller ticket run`: carry the ticket until it needs you (phase B)."""
    project = _project(args)
    ticket = chief.run(project, args.id, lane=args.lane, say=prompter.say)
    prompter.say(f"Ticket {ticket['id']:04d} is at {_label(ticket['stage'])}.\n"
                 f"  {next_hint(ticket)}")
    return 0


def close(args: Any, prompter: Prompter) -> int:
    project = _project(args)
    return _report(prompter, tickets.close(project, args.id, abandon_reason=args.abandon),
                   verb="Closed")


def _report(prompter: Prompter, ticket: dict, verb: str = "Moved") -> int:
    prompter.say(f"{verb}: ticket {ticket['id']:04d} is at {_label(ticket['stage'])}.\n"
                 f"  {next_hint(ticket)}")
    return 0
