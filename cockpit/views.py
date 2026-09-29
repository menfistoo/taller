"""The cockpit's two screens, and the two writes (spec 12).

Reading is `reading.py`'s job and writing is the library's; this module only
routes, and turns a refusal into something a person can act on.
"""

from __future__ import annotations

from flask import Blueprint, render_template

from . import check_token

bp = Blueprint("cockpit", __name__)


@bp.get("/")
def board():
    return render_template("board.html")


@bp.post("/ticket/<project>/<int:ticket_id>/approve")
def approve(project: str, ticket_id: int):
    check_token()
    return "", 501          # Task 4


@bp.post("/ticket/<project>/<int:ticket_id>/reject")
def reject(project: str, ticket_id: int):
    check_token()
    return "", 501          # Task 4
