"""Record every change to money, personal data or credentials.

Scaffolded because onboarding said this project handles one of them. Call
record() from the route that makes the change, after it succeeds.
"""

import database


def record(action: str, *, actor: str | None = None, detail: dict | None = None,
           path: str | None = None) -> None:
    database.insert_audit_event(action, actor, detail, path)
