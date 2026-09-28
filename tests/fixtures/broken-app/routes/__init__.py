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
