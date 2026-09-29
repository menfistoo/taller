"""The `taller` command: argument parsing, and nothing else (spec 3.5).

Every verb is a function in `taller.commands` taking parsed arguments and a
`Prompter`, so each is testable without argv and the acceptance test drives the
same code a terminal does.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from . import answers
from .errors import TallerError
from .prompter import AnswerSheetPrompter, Cancelled, NeedsAnswer, Prompter, TerminalPrompter

Handler = Callable[[argparse.Namespace, Prompter], int]

# An expected failure: the message is the whole story, so no traceback.
EXIT_CANCELLED = 1
EXIT_REFUSED = 2
EXIT_NEEDS_ANSWER = 3                  # a question nobody was there to answer
EXIT_INTERRUPTED = 130                 # the shell convention for Ctrl-C


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taller",
        description="Run your projects through an engineering team you direct.",
    )
    parser.add_argument(
        "--answers", metavar="FILE",
        help="answer questions from this JSON file instead of asking; an unanswered "
             "one stops with NEEDS <id>")
    verbs = parser.add_subparsers(dest="command", required=True, metavar="command")

    verbs.add_parser("setup", help="connect, find your projects and brands, choose languages")

    project = verbs.add_parser("project", help="create a project")
    project_verbs = project.add_subparsers(dest="action", required=True, metavar="action")
    new = project_verbs.add_parser("new", help="create a project, guided")
    new.add_argument("name", help="lowercase letters, digits and hyphens")
    new.add_argument("--path", help="the directory to create it in")
    new.add_argument("--no-open", action="store_true",
                     help="do not open the brief and swatch pages in a browser")

    brief = project_verbs.add_parser("brief", help="reopen the twelve answers")
    brief.add_argument("path", nargs="?", help="the project (default: the one you are in)")
    brief.add_argument("--no-open", action="store_true",
                       help="do not open the brief page in a browser")
    adopt = project_verbs.add_parser("adopt", help="bring an existing repository in, guided")
    adopt.add_argument("path", nargs="?", help="the repository (default: the one you are in)")
    adopt.add_argument("--name", help="the project's name (default: its directory's)")
    adopt.add_argument("--no-open", action="store_true",
                       help="do not open the brief and swatch pages in a browser")
    discover = project_verbs.add_parser("discover", help="what is new, moved or gone")
    discover.add_argument("roots", nargs="*", help="folders to look in (default: beside "
                                                   "the repository you are in)")
    show = project_verbs.add_parser("show", help="the brief and the queue")
    show.add_argument("path", nargs="?", help="the project (default: the one you are in)")

    brand = verbs.add_parser("brand", help="create a brand")
    brand_verbs = brand.add_subparsers(dest="action", required=True, metavar="action")
    brand_new = brand_verbs.add_parser("new", help="create a brand, guided")
    brand_new.add_argument("slug", nargs="?", help="the brand's short name")
    brand_new.add_argument("--no-open", action="store_true",
                           help="do not open the swatch page in a browser")

    brand_edit = brand_verbs.add_parser("edit", help="change a brand; its projects follow")
    brand_edit.add_argument("slug", nargs="?", help="the brand's short name")
    brand_edit.add_argument("--no-open", action="store_true",
                            help="do not open the swatch page in a browser")

    settings = verbs.add_parser("settings", help="every setting, and where it comes from")
    settings_verbs = settings.add_subparsers(dest="action", metavar="action")
    for verb, text in (("show", "list every effective setting"),
                       ("edit", "open the settings file in your editor")):
        sub = settings_verbs.add_parser(verb, help=text)
        sub.add_argument("--project", help="a project's own layer instead of the hub")
    setter = settings_verbs.add_parser("set", help="change one setting")
    setter.add_argument("key", help="dotted, as `taller settings` shows it")
    setter.add_argument("value", help="YAML: 400, true, [a, b]")
    setter.add_argument("--project", help="a project's own layer instead of the hub")

    ticket = verbs.add_parser("ticket", help="create and move tickets")
    ticket_verbs = ticket.add_subparsers(dest="action", required=True, metavar="action")

    def ticket_verb(verb: str, text: str, *, with_id: bool = True) -> argparse.ArgumentParser:
        sub = ticket_verbs.add_parser(verb, help=text)
        if with_id:
            sub.add_argument("id", type=int, help="the ticket's number")
        sub.add_argument("--path", help="the project (default: the one you are in)")
        return sub

    ticket_new = ticket_verb("new", "start a ticket, in your own words", with_id=False)
    ticket_new.add_argument("words", nargs="*", help="what should be done (asked if left out)")
    ticket_new.add_argument("--from-queue", action="store_true",
                            help="turn the project's first-version queue into tickets")
    ticket_new.add_argument("--kind", choices=("bug", "feature", "refactor", "question", "idea"),
                            help="name the kind yourself instead of asking the chief")
    ticket_verb("list", "open tickets", with_id=False).add_argument(
        "--all", action="store_true", help="closed ones too")
    ticket_verb("show", "one ticket, and what comes next")
    ticket_verb("transition", "move to the next stage").add_argument(
        "--lane", choices=("fast", "full"), help="chosen at triage")
    ticket_verb("run", "carry the ticket until it needs you").add_argument(
        "--lane", choices=("fast", "full"), help="override the lane chosen at triage")
    ticket_verb("approve", "approve at a checkpoint and move on")
    ticket_verb("reject", "reject at a checkpoint").add_argument(
        "--reason", help="why (asked if left out)")
    ticket_verb("resume", "pick a ticket up again after a stop or a crash")
    ticket_verb("close", "close a released ticket, or abandon one").add_argument(
        "--abandon", metavar="REASON", help="stop it here, with a reason")

    models_parser = verbs.add_parser("models", help="which models your account can reach")
    models_verbs = models_parser.add_subparsers(dest="action", required=True, metavar="action")
    models_verbs.add_parser("probe", help="ask each model one trivial question").add_argument(
        "--model", action="append", help="probe only this model (repeatable)")

    cockpit_parser = verbs.add_parser("cockpit", help="Taller's own pages, in a browser")
    cockpit_parser.add_argument("--port", type=int, help="the port to serve on (default 8765)")
    cockpit_parser.add_argument("--no-open", action="store_true",
                                help="do not open a browser window")

    stage_parser = verbs.add_parser("stage", help="bring a full ticket up on staging, on a "
                                                  "copy of the data")
    stage_parser.add_argument("id", type=int, help="the ticket's number")
    stage_parser.add_argument("--path", help="the project (default: the one you are in)")

    github_parser = verbs.add_parser("github", help="what GitHub says, and what to turn "
                                                    "on there")
    github_verbs = github_parser.add_subparsers(dest="action", required=True, metavar="action")
    for verb, text in (("status", "the checks and whether merging is protected"),
                       ("protect", "print the rule to require a pull request and a green check")):
        sub = github_verbs.add_parser(verb, help=text)
        sub.add_argument("--path", help="the project (default: the one you are in)")

    ci_parser = verbs.add_parser("ci", help="the model-free gates, for a CI run")
    ci_parser.add_argument("--base", help="what the change is measured against "
                                         "(default: origin/main)")
    ci_parser.add_argument("--head", help="the end of the change (default: HEAD)")
    ci_parser.add_argument("--mode", action="store_true",
                           help="print `full` or `ticket-files` for this push and stop")
    ci_parser.add_argument("--path", help="the project (default: the one you are in)")

    profiles_parser = verbs.add_parser("profiles", help="the hub's profiles, and keeping "
                                                      "them current")
    profiles_verbs = profiles_parser.add_subparsers(dest="action", required=True,
                                                    metavar="action")
    profiles_verbs.add_parser("list", help="which profiles this hub has, and whether each "
                                          "is current")
    profiles_update = profiles_verbs.add_parser(
        "update", help="add the settings a newer Taller brought, keeping your own edits")
    profiles_update.add_argument("name", help="the profile, as `taller profiles list` names it")

    resolve = verbs.add_parser("resolve", help="regenerate a project's generated files")
    resolve.add_argument("path", nargs="?", help="the project (default: the one you are in)")

    answer = verbs.add_parser("answer", help="answer the question a command stopped on "
                                             "(NEEDS <id>), from a chat")
    answer.add_argument("id", help="the question's id, as NEEDS printed it")
    answer.add_argument("value", nargs="+", help="the answer; several for several lines")

    hook_parser = verbs.add_parser("hook", help="what the Claude Code plugin's hooks call")
    hook_verbs = hook_parser.add_subparsers(dest="action", required=True, metavar="event")
    hook_verbs.add_parser("session-start", help="brief a chat that opens in a project")

    amend = verbs.add_parser("amend", help="commit a rule change and refresh what it reaches")
    amend.add_argument("--reason", help="why the rule changes (asked if left out)")
    amend.add_argument("--path", help="the project whose rules changed (default: the one "
                                      "you are in, if any)")

    scan = verbs.add_parser("scan", help="every rule over the whole tree: health figures")
    scan.add_argument("path", nargs="?", help="the project (default: the one you are in)")
    scan.add_argument("--all", action="store_true", help="every adopted project")

    doctor = verbs.add_parser("doctor", help="check the hub and every project")
    doctor.add_argument("--live", action="store_true",
                        help="make the trivial Claude dispatch even if it passed today")
    return parser


def _handler(args: argparse.Namespace) -> Handler:
    from .commands import (amend, brand, ci, doctor, hook, models, profiles, project,
                           resolve, scan, settings, setup, ticket)
    from .commands import github as github_command
    from .commands import cockpit as cockpit_command
    from .commands import stage as stage_command

    table: dict[tuple[str, str | None], Handler] = {
        ("setup", None): setup.run,
        ("project", "new"): project.new,
        ("project", "adopt"): project.adopt,
        ("project", "brief"): project.brief,
        ("project", "show"): project.show,
        ("project", "discover"): project.discover,
        ("brand", "new"): brand.run,
        ("brand", "edit"): brand.edit,
        ("settings", None): settings.run,
        ("settings", "show"): settings.run,
        ("settings", "set"): settings.run,
        ("settings", "edit"): settings.run,
        ("ticket", "new"): ticket.new,
        ("ticket", "list"): ticket.list_,
        ("ticket", "show"): ticket.show,
        ("ticket", "transition"): ticket.transition,
        ("ticket", "run"): ticket.run,
        ("ticket", "approve"): ticket.approve,
        ("ticket", "reject"): ticket.reject,
        ("ticket", "resume"): ticket.resume,
        ("ticket", "close"): ticket.close,
        ("models", "probe"): models.probe,
        ("ci", None): lambda args, prompter: (ci.mode if args.mode else ci.run)(args, prompter),
        ("stage", None): stage_command.run,
        ("cockpit", None): cockpit_command.run,
        ("github", "status"): github_command.status,
        ("github", "protect"): github_command.protect,
        ("profiles", "list"): profiles.list_,
        ("profiles", "update"): profiles.update,
        ("resolve", None): resolve.run,
        ("scan", None): scan.run,
        ("amend", None): amend.run,
        ("hook", "session-start"): hook.session_start,
        ("answer", None): _answer,
        ("doctor", None): doctor.run,
    }
    return table[(args.command, getattr(args, "action", None))]


def main(argv: list[str] | None = None, prompter: Prompter | None = None) -> int:
    words = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(words)
    managed: tuple[str, answers.Sheet] | None = None
    if prompter is None:
        # A console prints Unicode whatever the code page; a redirected stdout on
        # Windows is cp1252, which cannot hold ①. Write UTF-8 there instead.
        if hasattr(sys.stdout, "reconfigure") and not sys.stdout.isatty():
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        try:
            prompter, managed = _prompter(args, words)
        except TallerError as exc:
            print(f"taller: {exc}", flush=True)
            return EXIT_REFUSED
    try:
        code = _run_guarded(args, prompter)
    except NeedsAnswer as exc:
        again = (f"This question comes again in this run (time {exc.occurrence}); give "
                 f"the answer for this time.\n" if exc.occurrence > 1 else "")
        if managed:
            answers.needs(managed[0], os.getcwd(), words, managed[1])
            prompter.say(f"NEEDS {exc.qid}\n{exc.prompt}\n{again}"
                         f'Answer with: taller answer {exc.qid} "<answer>" (one quoted '
                         f"argument per line when it asks for several), then run the same "
                         f"command again.")
        else:
            prompter.say(f"NEEDS {exc.qid}\n{exc.prompt}\n{again}"
                         f'Put the answer in the answers file as "{exc.qid}": ... and run '
                         f"the same command again.")
        return EXIT_NEEDS_ANSWER
    except BaseException:
        if managed:
            answers.finished(managed[0])      # whatever happened, these answers are spent
        raise
    if managed:
        answers.finished(managed[0])
    return code


def _run_guarded(args: argparse.Namespace, prompter: Prompter) -> int:
    """The command, with every expected failure turned into its exit code."""
    try:
        return _handler(args)(args, prompter)
    except NeedsAnswer:
        raise                                   # main reports it: it knows the sheet
    except Cancelled as exc:
        prompter.say(str(exc))
        return EXIT_CANCELLED
    except TallerError as exc:
        prompter.say(f"taller: {exc}")
        return EXIT_REFUSED
    except KeyboardInterrupt:
        prompter.say("Stopped. Everything already done is saved; run the command again "
                     "to carry on.")
        return EXIT_INTERRUPTED


def _prompter(args: argparse.Namespace, words: list[str]
              ) -> tuple[Prompter, tuple[str, answers.Sheet] | None]:
    """Who answers this command's questions.

    `--answers FILE`: the file. Inside a Claude Code chat (`CLAUDECODE` is set in
    its shell): the answers Taller keeps for this very command, which the chat
    adds to with `taller answer`. Anyone else - a terminal, an IDE console that
    is not a terminal - is asked at the keyboard, as before (plugin review, I1).
    """
    if args.answers:
        return AnswerSheetPrompter(_load_answers(Path(args.answers))), None
    if os.environ.get("CLAUDECODE") and args.command not in ("answer", "hook"):
        sheet_key = answers.key(os.getcwd(), words)
        sheet = answers.load(sheet_key)
        return AnswerSheetPrompter(sheet, repeats=True), (sheet_key, sheet)
    return TerminalPrompter(), None


def _answer(args: argparse.Namespace, prompter: Prompter) -> int:
    value: Any = args.value[0] if len(args.value) == 1 else list(args.value)
    record = answers.add(args.id, value)
    prompter.say(f"Noted {args.id}. Now run the same command again: "
                 f"taller {' '.join(record.get('argv') or [])}")
    return 0


def _load_answers(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}                       # a first run: every question will be NEEDS
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    except ValueError as exc:
        raise TallerError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise TallerError(f"{path} must hold a JSON object of question id to answer.")
    return data


if __name__ == "__main__":
    sys.exit(main())
