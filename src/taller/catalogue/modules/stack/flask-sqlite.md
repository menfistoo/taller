> Flask 3 serving Jinja2 and Bootstrap 5 over SQLite in WAL mode, behind gunicorn in Docker.

## Runtime shape

Python 3.11+, Flask 3.0+, Jinja2 templates rendered server side, Bootstrap 5 for
layout, SQLite as the only datastore. In production gunicorn runs the WSGI app and
a reverse proxy terminates TLS in front of it; Docker Compose starts both. There is
no client-side framework and no API layer: a route renders a template or redirects.

Keep it that way unless a ticket says otherwise. Every part of this stack is chosen
so one person can read the whole request path in an afternoon, and an added layer
costs that property permanently.

## The database

SQLite runs in WAL mode so a reader never blocks a writer. Set the journal mode and
a `busy_timeout` at connection time, not once at build time: a fresh database file
created by a migration or a test would otherwise come up in the default mode and
serialise every read behind the current write.

**Always open a connection through a context manager.** A leaked connection holds
its WAL read snapshot open, and the WAL file then grows without bound because no
checkpoint can retire the pages it still references. The manager is also the only
place that can guarantee the mode settings above are applied.

**Set `row_factory = sqlite3.Row`.** Positional tuple access binds callers to the
column order of a `SELECT`, so adding a column to a query silently shifts the
meaning of every index after it. `Row` makes that class of bug unrepresentable.

**Read-then-write goes inside one `BEGIN IMMEDIATE` transaction.** SQLite starts a
deferred transaction by default, which takes a read lock first and upgrades on the
write. Two processes that both read a counter and then write it back can both hold
the read lock, and one of them loses its update or dies with "database is locked"
halfway through. `BEGIN IMMEDIATE` takes the write lock up front, so the loser
waits instead of corrupting the result.

**All SQL lives in one module.** Not because layering is elegant, but because it is
the only way a reviewer can answer "what touches this table" by reading one file.
Routes call named functions; they do not build SQL.

## Deployment

The database file lives in a mounted volume, never inside the image. An image is
rebuilt and replaced on every deploy, so data baked into one is data you will
delete without noticing. Configuration reaches the container through the
environment, and the compose file names the volume explicitly so a `down -v` is the
only way to lose it.
