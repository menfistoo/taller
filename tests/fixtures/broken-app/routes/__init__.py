"""Routes. The flask-sqlite profile allows `database` and `utils.*` only."""

from flask import Blueprint, render_template

import app  # constitution.layer-violation: routes may not import the app module
import database

bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/ledger")
def ledger():
    # No permission check: the security gate's case (spec 15.2).
    rows = database.all_entries()
    return render_template("index.html", rows=rows)


@bp.get("/broken")
def broken():
    # Raises on render: pytest has no test for it, smoke must catch it (spec 15.2).
    return render_template("broken.html")
