"""Access control. Who the users are and how they sign in is a ticket, not a
scaffold; this is the one check every protected route goes through."""

from functools import wraps

from flask import abort, session


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user_id") is None:
            abort(401)
        return view(*args, **kwargs)
    return wrapped
