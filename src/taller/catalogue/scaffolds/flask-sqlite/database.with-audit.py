"""All SQL lives here. Open a connection only through get_db()."""

import json
import sqlite3
from contextlib import contextmanager

from flask import current_app

# Tables are added here, by ticket. The audit log is append-only: nothing
# updates or deletes a row of it.
SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id     INTEGER PRIMARY KEY,
    at     TEXT NOT NULL DEFAULT (datetime('now')),
    actor  TEXT,
    action TEXT NOT NULL,
    detail TEXT
);
"""


@contextmanager
def get_db(path: str | None = None):
    """A connection in WAL mode with Row access; committed on success.

    Always through this manager: a leaked connection pins its WAL snapshot and the
    WAL file then grows without bound.
    """
    conn = sqlite3.connect(path or current_app.config["DATABASE"], timeout=5)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: str | None = None) -> None:
    with get_db(path) as conn:
        conn.executescript(SCHEMA)


def insert_audit_event(action: str, actor: str | None, detail: dict | None,
                       path: str | None = None) -> None:
    payload = json.dumps(detail, sort_keys=True) if detail is not None else None
    with get_db(path) as conn:
        conn.execute(
            "INSERT INTO audit_log (actor, action, detail) VALUES (?, ?, ?)",
            (actor, action, payload),
        )


def audit_events(path: str | None = None) -> list[sqlite3.Row]:
    with get_db(path) as conn:
        return conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()
