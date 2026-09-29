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

from flask import Flask, abort, render_template, request, session

TOKEN_FIELD = "_token"
TOKEN_KEY = "token"
# The only names this server answers to. A website can point its own hostname at
# 127.0.0.1, and a browser then treats that site as SAME ORIGIN as the cockpit -
# the Strict cookie is sent, and its script can read the token straight out of
# the page. Binding the socket to this machine does not stop that; checking the
# name the browser asked for does.
THIS_MACHINE = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def create_app(*, testing: bool = False) -> Flask:
    app = Flask(__name__)
    # A fresh key each start: a session that does not survive a restart is
    # exactly right for a page that holds no login.
    app.config.update(SECRET_KEY=secrets.token_hex(32), TESTING=testing,
                      SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_HTTPONLY=True)

    from . import views

    app.register_blueprint(views.bp)
    app.before_request(check_host)
    app.register_error_handler(404, _not_found)
    app.register_error_handler(500, _went_wrong)
    app.jinja_env.globals.update(token_field=TOKEN_FIELD, token=lambda: _token())
    return app


def check_host() -> Any:
    """Refuse anything that asked for this server under another name."""
    if hostname(request.host) not in THIS_MACHINE:
        abort(400, "This page is served to this machine only, and something asked for it "
                   f"as {request.host!r}. Open it as http://127.0.0.1:<port>/.")
    return None


def hostname(host: str) -> str:
    """The name out of a `Host` header, without its port. `[::1]:8765` keeps its
    brackets, which is how a browser writes a literal IPv6 address."""
    if host.startswith("["):
        return host[:host.find("]") + 1] or host
    return host.split(":", 1)[0]


def _not_found(exc: Any) -> tuple[str, int]:
    return render_template("problem.html", heading="That is not here",
                           detail=getattr(exc, "description", str(exc))), 404


def _went_wrong(exc: Any) -> tuple[str, int]:
    # Never the exception's own text: an unexpected failure's message is for a
    # log, and what she needs is what to do next.
    return render_template(
        "problem.html", heading="Taller could not build this page",
        detail="Something unexpected went wrong reading this. The terminal that is "
               "running `taller cockpit` printed the details; `taller doctor` is the "
               "next thing to try."), 500


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
