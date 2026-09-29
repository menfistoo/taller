"""The cockpit: Taller's own pages, on this machine only (spec 12).

Flask and Jinja2, Bootstrap 5 from its CDN, **no database**. Every figure comes
from the same library the CLI uses - the registry, each project's `status.yml`,
the verdict files and git - and every write goes through the same library call
under the same locks (spec 10.3). Approving here and approving in a terminal are
one act on one file.

**No authentication, and that is deliberate** (spec 1.1): one operator, bound to
127.0.0.1. It is not the same as no protection. A page on any other website can
make her browser post to 127.0.0.1, so every form carries a token this
application made, and every write checks it.
"""

from __future__ import annotations

import secrets
from typing import Any

from flask import Flask, abort, request, session

TOKEN_FIELD = "_token"
TOKEN_KEY = "token"


def create_app(*, testing: bool = False) -> Flask:
    app = Flask(__name__)
    # A fresh key each start: a session that does not survive a restart is
    # exactly right for a page that holds no login.
    app.config.update(SECRET_KEY=secrets.token_hex(32), TESTING=testing,
                      SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_HTTPONLY=True)

    from . import views

    app.register_blueprint(views.bp)
    app.jinja_env.globals.update(token_field=TOKEN_FIELD, token=lambda: _token())
    return app


def _token() -> str:
    """This session's token, made on first sight."""
    if TOKEN_KEY not in session:
        session[TOKEN_KEY] = secrets.token_urlsafe(32)
    return str(session[TOKEN_KEY])


def check_token() -> None:
    """Refuse a write whose token is not the one this application handed out."""
    given = request.form.get(TOKEN_FIELD, "")
    expected = session.get(TOKEN_KEY)
    if not expected or not given or not secrets.compare_digest(given, str(expected)):
        abort(400, "This form did not carry the cockpit's token, so nothing was done. "
                   "Open the page again and use its own buttons.")
