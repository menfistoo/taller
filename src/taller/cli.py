"""The `taller` command: argument parsing, and nothing else (spec 3.5).

Every verb is a function in `taller.commands` taking parsed arguments and a
`Prompter`, so each is testable without argv and the acceptance test drives the
same code a terminal does.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from .errors import TallerError
from .prompter import Cancelled, Prompter, TerminalPrompter

Handler = Callable[[argparse.Namespace, Prompter], int]

# An expected failure: the message is the whole story, so no traceback.
EXIT_CANCELLED = 1
EXIT_REFUSED = 2
EXIT_INTERRUPTED = 130                 # the shell convention for Ctrl-C


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taller",
        description="Run your projects through an engineering team you direct.",
    )
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

    resolve = verbs.add_parser("resolve", help="regenerate a project's generated files")
    resolve.add_argument("path", nargs="?", help="the project (default: the one you are in)")

    scan = verbs.add_parser("scan", help="every rule over the whole tree: health figures")
    scan.add_argument("path", nargs="?", help="the project (default: the one you are in)")
    scan.add_argument("--all", action="store_true", help="every adopted project")

    doctor = verbs.add_parser("doctor", help="check the hub and every project")
    doctor.add_argument("--live", action="store_true",
                        help="make the trivial Claude dispatch even if it passed today")
    return parser


def _handler(args: argparse.Namespace) -> Handler:
    from .commands import (brand, doctor, models, project, resolve, scan, settings, setup,
                           ticket)

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
        ("resolve", None): resolve.run,
        ("scan", None): scan.run,
        ("doctor", None): doctor.run,
    }
    return table[(args.command, getattr(args, "action", None))]


def main(argv: list[str] | None = None, prompter: Prompter | None = None) -> int:
    args = build_parser().parse_args(argv)
    if prompter is None:
        # A console prints Unicode whatever the code page; a redirected stdout on
        # Windows is cp1252, which cannot hold ①. Write UTF-8 there instead.
        if hasattr(sys.stdout, "reconfigure") and not sys.stdout.isatty():
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        prompter = TerminalPrompter()
    try:
        return _handler(args)(args, prompter)
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


if __name__ == "__main__":
    sys.exit(main())
