"""Routes render a template or redirect. SQL lives in database.py."""

from flask import Blueprint, render_template

bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    return render_template("index.html")
