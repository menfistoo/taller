"""The cockpit's two screens, and the two writes (spec 12).

Reading is `reading.py`'s job and writing is the library's; this module only
routes, and turns a refusal into something a person can act on.
"""

from __future__ import annotations

from flask import Blueprint, abort, render_template

from taller.errors import TallerError

from . import check_token, reading

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
    return render_template("ticket.html", page=page)


@bp.post("/ticket/<project>/<int:ticket_id>/approve")
def approve(project: str, ticket_id: int):
    check_token()
    return "", 501          # Task 4


@bp.post("/ticket/<project>/<int:ticket_id>/reject")
def reject(project: str, ticket_id: int):
    check_token()
    return "", 501          # Task 4
