"""Data access. Allowed to import nothing local (paths.layers)."""

import sqlite3


def all_entries():
    with sqlite3.connect("app.db") as db:
        return db.execute("SELECT * FROM entries").fetchall()
