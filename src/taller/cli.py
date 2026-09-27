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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taller",
        description="Run your projects through an engineering team you direct.",
    )
    verbs = parser.add_subparsers(dest="command", required=True, metavar="command")

    verbs.add_parser("setup", help="connect GitHub and choose your languages")

    project = verbs.add_parser("project", help="create a project")
    project_verbs = project.add_subparsers(dest="action", required=True, metavar="action")
    new = project_verbs.add_parser("new", help="create a project, guided")
    new.add_argument("name", help="lowercase letters, digits and hyphens")
    new.add_argument("--path", help="the directory to create it in")
    new.add_argument("--no-open", action="store_true",
                     help="do not open the brief and swatch pages in a browser")

    brand = verbs.add_parser("brand", help="create a brand")
    brand_verbs = brand.add_subparsers(dest="action", required=True, metavar="action")
    brand_new = brand_verbs.add_parser("new", help="create a brand, guided")
    brand_new.add_argument("slug", nargs="?", help="the brand's short name")
    brand_new.add_argument("--no-open", action="store_true",
                           help="do not open the swatch page in a browser")

    resolve = verbs.add_parser("resolve", help="regenerate a project's generated files")
    resolve.add_argument("path", nargs="?", help="the project (default: the one you are in)")

    doctor = verbs.add_parser("doctor", help="check the hub and every project")
    doctor.add_argument("--live", action="store_true",
                        help="make the trivial Claude dispatch even if it passed today")
    return parser


def _handler(args: argparse.Namespace) -> Handler:
    from .commands import brand, doctor, project, resolve, setup

    table: dict[tuple[str, str | None], Handler] = {
        ("setup", None): setup.run,
        ("project", "new"): project.new,
        ("brand", "new"): brand.run,
        ("resolve", None): resolve.run,
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


if __name__ == "__main__":
    sys.exit(main())
