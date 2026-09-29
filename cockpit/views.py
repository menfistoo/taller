"""The cockpit's two screens, and the two writes (spec 12).

Reading is `reading.py`'s job and writing is the library's; this module only
routes, and turns a refusal into something a person can act on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from taller import tickets
from taller.errors import LockTimeout, TallerError

from . import check_token, reading, runs

bp = Blueprint("cockpit", __name__)


@bp.get("/")
def board():
    return render_template("board.html", board=reading.board())


@bp.get("/ticket/<project>/<int:ticket_id>")
def ticket(project: str, ticket_id: int):
    try:
        page = reading.ticket_page(project, ticket_id)
    except TallerError as exc:
        # A number she typed, or a ticket that never existed: her words back, not
        # a stack trace.
        abort(404, str(exc))
    return render_template("ticket.html", page=page,
                           run=runs.progress(runs.run_id(page["project"], ticket_id)))


@bp.post("/ticket/<project>/<int:ticket_id>/approve")
def approve(project: str, ticket_id: int):
    """Approve at this stage's checkpoint, then let the work carry on.

    The approval is `tickets.approve` - the same call the terminal makes, under
    the same lock - and the work that follows is `taller ticket run` in its own
    process. Nothing here waits for it: the page shows where it has got to and
    refreshes itself while it is going.
    """
    def act(path: Path, name: str) -> None:
        tickets.approve(path, ticket_id)
        runs.start(path, name, ticket_id)

    return _write(project, ticket_id, act)


@bp.post("/ticket/<project>/<int:ticket_id>/reject")
def reject(project: str, ticket_id: int):
    """Say no, in her own words. The words are the whole point: the next attempt
    reads them, so a rejection with nothing in it is refused rather than kept."""
    reason = request.form.get("reason", "")

    def act(path: Path, name: str) -> None:
        tickets.reject(path, ticket_id, reason)

    return _write(project, ticket_id, act)


def _write(project: str, ticket_id: int, act: Callable[[Path, str], None]) -> Any:
    """Check the token, do the write, and come back to the ticket's page.

    Every refusal the library can make - a checkpoint that is not one, a
    rejection with no reason, a project someone else is working on - arrives
    here as a TallerError carrying a sentence meant for her, so it is shown as
    that sentence and nothing is left half done.
    """
    check_token()
    try:
        entry = reading.entry_for(project)
        act(Path(entry["path"]), entry["name"])
    except LockTimeout as exc:
        flash(f"Taller is busy with this project, so nothing was changed. {exc}", "warning")
    except TallerError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("cockpit.ticket", project=project, ticket_id=ticket_id))
