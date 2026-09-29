# Taller Phase E (part one) — the cockpit's Board and Ticket

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner can see every ticket of every project on one page, open one, read what was asked, what the gates found and what changed, and approve or reject it there — and the work carries on without her leaving the browser.

**Architecture:** A small Flask application under `cockpit/`, started by `taller cockpit`, bound to `127.0.0.1`. **No database and no second system:** it imports the same library the CLI does, reads `~/.taller/projects.json` and each project's `.taller/work/*/status.yml`, and writes through `tickets.approve` / `tickets.reject` under the same locks (§12). Approving starts `taller ticket run` as a separate detached process and the page follows its output — the chief is never hosted inside the web server (§3.1).

**Tech Stack:** Python 3.11, Flask 3.0 + Jinja2, Bootstrap 5 from its CDN, no JavaScript framework. Tests drive Flask's test client; no browser, no network.

**Spec:** [2026-09-26-taller-design.md](../specs/2026-09-26-taller-design.md) — §12 is the scope contract (the six screens; this plan builds the first two), §3.1 (`taller cockpit` is a web server, not the chief), §10.3 (the locks the cockpit shares), §7.1 (what `status.yml` holds), §7.4 (verdict files), §1.1's "not multi-user: no auth, bound to 127.0.0.1", goal G7 made visible.

**Builds on:** Phases A, D, B, C, the plugin and F — one commit on `main`, 916 tests. Conventions hold: TDD, plain-language text, English in Taller's own interface, UTF-8 everywhere, no real `claude` in tests.

## The owner's decisions (2026-09-29)

- **Approving in the browser starts the next stretch of work** and the page shows where it has got to. The run is a separate process; the page reads its output.
- **Board and Ticket first.** Spend, Constitution, Settings, Health and the onboarding form are part two, listed under Deferred.

## Global Constraints

- Binds `127.0.0.1` only, no authentication, single operator (§1.1). A port already in use is reported plainly, never bound over.
- No database (§12). Every figure comes from the registry, `status.yml`, the verdict files and git.
- Every write goes through the same library call the CLI uses, under §10.3's locks: approving in the browser and approving in the terminal are one act on one file.
- Taller's own interface is in English and carries **no brand**: the cockpit never renders her brand tokens (G9).
- The cockpit never hosts the chief: a run is `taller ticket run` in its own process (§3.1).
- Every form carries a token checked on submission: a page on another site must not be able to make her cockpit act.

## Review Focus

1. **A page on another website posting to `127.0.0.1`** — a browser will happily send it. Without a checked token, any open tab could approve a ticket. *Pinned in Task 1.*
2. **A run already holding the project lock** (started here, from a chat, or in a terminal) — a second approval must say "Taller is busy" in plain words, not fail with a traceback or wait for ever. *Pinned in Task 4.*
3. **A ticket whose branch and working copy are gone** — after a rejection, or a `git clean`. The Ticket screen must still show what `main` holds and say the rest is gone. *Pinned in Task 3.*
4. **A registered project whose folder has moved or been deleted** — the Board must show it as unavailable and still render every other project. *Pinned in Task 2.*
5. **A very large plan or diff** — a 4,000-line plan, a 900-file change. The page must stay quick and say it cut something, rather than sending megabytes to the browser. *Pinned in Task 3.*

---

## File Structure

```
cockpit/__init__.py            create_app(): the Flask application, its token, its error pages
cockpit/views.py               the two screens and the two writes
cockpit/reading.py             what the screens read: projects, tickets, one ticket's papers
cockpit/runs.py                starting `taller ticket run` and reading how far it has got
cockpit/templates/base.html    Bootstrap 5 from the CDN, no brand
cockpit/templates/board.html   every ticket by stage
cockpit/templates/ticket.html  one ticket: the ask, the plan, the verdicts, the diff, the buttons
src/taller/commands/cockpit.py `taller cockpit [--port N] [--no-open]`
src/taller/tickets.py          `on_branch()` promoted from the three private copies
pyproject.toml                 flask>=3.0; the cockpit package ships
tests/unit/test_cockpit_reading.py  test_cockpit_board.py  test_cockpit_ticket.py
tests/unit/test_cockpit_writes.py   tests/acceptance/test_cockpit_flow.py
```

---

### Task 1: The application, and `taller cockpit`

**Files:** Create `cockpit/__init__.py`, `cockpit/templates/base.html`, `src/taller/commands/cockpit.py`, `tests/unit/test_cockpit_app.py`. Modify `src/taller/cli.py`, `pyproject.toml`.

**Interfaces — produces:**

```python
def create_app(*, testing: bool = False) -> flask.Flask   # cockpit/__init__.py
TOKEN_FIELD = "_token"                                    # the field every form carries
def check_token() -> None                                 # aborts 400 when it does not match
# taller cockpit [--port N] [--no-open]; default port 8765
```

The token is a random value made when the application starts, kept in Flask's session, rendered into every form and compared on every POST — a page on another site cannot read it (Review Focus 1). `base.html` loads Bootstrap 5 from its CDN and carries no brand token. A port in use is reported with the port number and the flag to change it.

- [ ] **Step 1: Failing tests** — `test_the_app_serves_the_board_at_the_root`; `test_a_post_without_the_token_is_refused` (400, and nothing written); `test_a_post_with_the_token_is_accepted`; `test_the_page_carries_no_brand_token` (no `var(--brand`, no `tokens.css`); `test_cockpit_binds_localhost_only` (the call `app.run` is given `host="127.0.0.1"`); `test_a_port_in_use_is_reported_not_bound_over` (a socket holding the port → exit 2 naming `--port`).
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(cockpit): the application, bound to this machine, with a token on every form`

### Task 2: Reading, and the Board

**Files:** Create `cockpit/reading.py`, `cockpit/views.py`, `cockpit/templates/board.html`, `tests/unit/test_cockpit_reading.py`, `tests/unit/test_cockpit_board.py`.

**Interfaces — produces:**

```python
def projects() -> list[dict]      # {"name", "path", "available": bool, "tickets": [...], "problem": str}
def board() -> dict               # {"stages": [ {"stage", "label", "tickets": [...]} ], "projects": [...] }
```

Every ticket of every adopted project, in columns by stage ① → ⑫, closed ones left out. A ticket shows its number, title, project, lane, and a mark when a checkpoint is `pending`, when `blocked`, or when `effective_sync` is `pending`. A project whose folder is gone is listed with the reason and does not stop the rest (Review Focus 4). A blocked ticket appears in its own column with its reason (§8.4).

- [ ] **Step 1: Failing tests** — `test_every_open_ticket_of_every_project_is_on_the_board`; `test_a_closed_ticket_is_not`; `test_a_ticket_waiting_for_her_is_marked`; `test_a_blocked_ticket_shows_its_reason`; `test_an_unsynced_ticket_is_marked`; `test_a_project_whose_folder_is_gone_does_not_break_the_board` (it is listed as unavailable, the other project's tickets are still there); `test_the_board_names_the_stage_each_column_is`.
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(cockpit): the board - every ticket, every project, by stage`

### Task 3: The Ticket screen

**Files:** Create `cockpit/templates/ticket.html`, `tests/unit/test_cockpit_ticket.py`. Modify `cockpit/reading.py`, `cockpit/views.py`, `src/taller/tickets.py` (promote `on_branch`), `src/taller/prs.py` and `src/taller/chief.py` (use it).

**Interfaces — produces:**

```python
# tickets.py
def on_branch(project: Path, ticket: Mapping, name: str) -> str | None   # a file from the ticket's branch
# cockpit/reading.py
def ticket_page(project_name: str, ticket_id: int) -> dict
#   {"ticket", "words", "plan", "review", "verdicts": [...], "findings": [...],
#    "diff": {"files": [...], "cut": bool}, "notes": [...], "gone": list[str]}
PAPER_MAX = 20_000        # characters of any one paper shown
DIFF_FILES_MAX = 50       # files listed before the rest is summarised
```

The ask (from `ticket.md` on `main`), the plan and the review summary, every verdict with its counts and its findings (from `gates/*.md` on the branch), the changed files with how many lines each, and the last notes. `on_branch` replaces the three private copies of the same three lines in `prs.py`, `chief.py` and here. A paper or a diff over its limit is cut with a line saying so (Review Focus 5). A branch or working copy that is gone is named in `gone` and the rest still renders (Review Focus 3).

- [ ] **Step 1: Failing tests** — `test_the_page_shows_the_ask_the_plan_and_the_review`; `test_every_verdict_and_its_findings_are_shown`; `test_the_changed_files_are_listed_with_their_line_counts`; `test_a_ticket_whose_branch_is_gone_still_renders` (the ask and the notes are there, `gone` names the branch); `test_a_huge_plan_is_cut_with_a_line_saying_so`; `test_a_diff_of_many_files_is_summarised`; `test_on_branch_is_one_function_now` (`prs` and `chief` call `tickets.on_branch`).
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(cockpit): one ticket - the ask, the plan, the verdicts, the change`

### Task 4: Approving, rejecting, and carrying on

**Files:** Create `cockpit/runs.py`, `tests/unit/test_cockpit_writes.py`. Modify `cockpit/views.py`, `cockpit/templates/ticket.html`.

**Interfaces — produces:**

```python
def start(project: Path, name: str, ticket_id: int) -> str      # a run id; starts `taller ticket run`
def progress(run_id: str) -> dict   # {"running": bool, "lines": [str], "code": int | None}
RUNS_DIR = paths.run_dir() / "cockpit-runs"
```

`POST /ticket/<project>/<id>/approve` calls `tickets.approve`, then `runs.start`; the page then shows the run's output, refreshing itself while it is running (a meta refresh — no JavaScript framework). `POST …/reject` requires a reason, and refuses with a message when it is empty rather than rejecting with none. A `LockTimeout` from either becomes the plain "Taller is busy" message (Review Focus 2). The run is detached, its output kept in `RUNS_DIR/<project>-<id>.log`, and `progress` reads that file and the process's state — the web server never waits for it.

- [ ] **Step 1: Failing tests** — `test_approving_writes_the_approval_and_starts_a_run` (the stubbed runner is asked for `ticket run <id>`); `test_rejecting_needs_a_reason` (empty → 400-ish message, nothing written); `test_rejecting_records_her_words`; `test_a_busy_project_says_so_plainly` (the lock held → the page says Taller is busy, no traceback); `test_the_page_shows_a_run_still_going_and_then_its_result`; `test_the_run_is_not_waited_for` (the request returns while the fake run is still open); `test_only_the_owner_decides` (a GET never approves).
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(cockpit): approve or reject, and the work carries on`

### Task 5: The proof — a ticket carried from the browser

**Files:** Create `tests/acceptance/test_cockpit_flow.py`.

On an empty HOME with the stub `claude`: `project new`, a ticket run to the review checkpoint by the chief, then **through the test client only** — the Board shows it waiting; the Ticket page shows the plan, the four verdicts and the changed file; approving writes the approval and starts a run (the runner stubbed to record its argv); the Board then shows the ticket at its next stage. A second acceptance case rejects with a reason and asserts the reason reached `notes.md` and the ticket went back to ② triage. Finally `taller doctor` is still green, and the cockpit wrote nothing but what the library wrote.

- [ ] Write · run · suite green · commit `test(acceptance): a ticket seen, approved and carried on from the browser`

---

## Deferred, recorded rather than forgotten

| Item | Why not now |
|---|---|
| Spend, Constitution, Settings and Health screens (§12) | Her decision: the two daily screens first, then the rest once she has used them |
| The onboarding wizard as a web form (§12) | Same; the twelve questions already work in the terminal and in a chat |
| Live progress without a page refresh (server-sent events) | A meta refresh is enough for one operator; no framework earns its place yet |
| Showing the diff with syntax colour | Reading it is the job; colour is polish |
| `taller cockpit` served over Tailscale | §1.1 binds it to this machine on purpose |
