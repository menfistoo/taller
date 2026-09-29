# Taller Phase D — Tickets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A ticket is a set of files on `main` that moves through the twelve stages by command, survives a killed session, and is mirrored to a GitHub issue — so the queue `project new` writes becomes real, resumable work.

**Architecture:** One library module, `tickets.py`, owns the ticket: its `status.yml` schema, the stage machine, and every write, which goes through `gitio.commit_to_main()` under the project lock. Tickets are always **read from `main`** (`git show main:<path>`), never from the owner's working tree, which may be on a ticket branch. A thin `commands/ticket.py` drives it; `issues.py` wraps `gh` for mirroring. Until the chief exists (Phase B), the owner answers what the chief will later decide — the kind at ①, the lane at ② — and moves the ticket with commands.

**Tech Stack:** Python 3.11, PyYAML, git, `gh` (optional), pytest. No new dependency.

**Spec:** [2026-09-26-taller-design.md](../specs/2026-09-26-taller-design.md) — §10.4's Phase D row is the scope contract: *tickets, `status.yml`, `sync` handling, transitions, issue mirroring*. Also §7.1, §7.2, §7.6, §8.1–§8.4, §14, §15.4, §16 criteria 4 and 11.

**Builds on:** Phase A ([plan](2026-09-26-phase-a-foundations.md)), branch `phase-a/foundations`. The conventions of that plan hold: TDD, code and messages in English, plain-language prompts, UTF-8 at every subprocess boundary, no real inference in tests.

## Global Constraints

- Twelve stages, names and order exactly: `intake triage design build gates smoke review pr staging merge release close` (§8.1). `stage` in `status.yml` holds the **name**.
- Lanes: `fast` = stages 1 2 4 5 6 7 8 10 11 12; `full` = all twelve (§8.2). A ticket is never demoted from `full` to `fast`.
- Checkpoints: `design` ③ and `staging` ⑨ lane-dependent (`skipped` on fast); `review` ⑦ and `release` ⑪ unconditional. Values: `pending | approved | rejected | skipped`.
- `blocked` is a flag, never a stage: `null` or `{reason, at_stage, since}` (§8.4).
- `kind`: `bug | feature | refactor | question | idea`. `sync`: `ok | local | pending`.
- Directory `.taller/work/NNNN-slug/`, id zero-padded to 4; branch `ticket/NNNN-slug` (§8.3).
- `ticket.md`, `status.yml`, `notes.md` and `rejected/**` are written to `main` only through `gitio.commit_to_main()` (§7.2). `notes.md` is append-only.
- Every read-modify-write of a ticket under `locking.project_lock()` (§10.3).
- A `gh` failure never stops a local stage (§14).

## Review Focus

1. **The owner's checkout is on a ticket branch** when a ticket command runs — every read must come from `main`, or `list` shows stale tickets and `new` reuses an id. *Pinned in Task 1.*
2. **Two tickets created at once** from two terminals — the id is chosen under the project lock from `main` as it is at that moment. *Pinned in Task 1.*
3. **A title that slugs badly** — accents, `¿…?`, emoji, 200 characters, only punctuation. Expect `arreglar-el-boton`, a 40-character cap, and `ticket` when nothing is left. *Pinned in Task 1.*
4. **A hand-edited or broken `status.yml`** — `load` names the file and the problem; `list` reports it and goes on; `doctor` fails it. Never a traceback. *Pinned in Tasks 1 and 5.*
5. **`gh` missing, signed out or offline at ①** — the ticket is created, the issue is retried at the next transition, and never created twice. *Pinned in Task 3.*

---

## File Structure

```
src/taller/
├── tickets.py          schema, read-from-main, create, stage machine, notes   (§7, §8)
├── issues.py           gh issue create / close, repo from origin              (§13)
├── gitio.py            + .taller/queue.yml on the allowed list                (§11.4)
├── doctor.py           + the phase D row of §15.4
├── paths.py            + ticket_worktree(project, ticket_dir)
├── commands/ticket.py  new, list, show, transition, approve, reject, resume, close
└── cli.py              + `ticket` verbs
tests/unit/test_tickets.py  test_ticket_stages.py  test_issues.py  test_ticket_command.py
tests/acceptance/test_ticket_lifecycle.py
```

**Why `issues.py` is separate:** it is the only part that talks to GitHub, so it is where a failure must be absorbed; `tickets.py` stays testable with no `gh` at all.

---

### Task 1: The ticket on disk — schema, reads from `main`, create, notes

**Files:**
- Create: `src/taller/tickets.py`, `tests/unit/test_tickets.py`
- Modify: `src/taller/gitio.py` (allow `.taller/queue.yml`), spec §7.2 table (one row)

**Interfaces — produces:**

```python
Ticket = dict[str, Any]                       # exactly status.yml's keys, §7.1
STAGES: tuple[str, ...]                       # the twelve names, in order
LANE_STAGES: dict[str, tuple[str, ...]]       # "fast" / "full"
CHECKPOINT_AT: dict[str, str]                 # stage -> checkpoint: design, review, staging, release
KINDS: tuple[str, ...]

def slugify(title: str) -> str                               # ≤ 40 chars, ascii, never empty
def ticket_dir(ticket: Ticket) -> str                         # ".taller/work/0043-danger-color"
def read_main(project: Path, relative: str) -> bytes | None   # git show main:<path>
def list_tickets(project: Path) -> tuple[list[Ticket], list[str]]   # (tickets by id, problems)
def load(project: Path, ticket_id: int) -> Ticket             # ConfigError naming the file
def create(project: Path, *, title: str, words: str, kind: str) -> Ticket
def write(project: Path, ticket: Ticket, message: str, *,
          note: str | None = None, extra: Mapping[str, bytes] = {}) -> Ticket
def render_status(ticket: Ticket) -> bytes                    # fixed key order, LF
```

`write` is the only path to `main`: under the project lock it renders `status.yml`, appends `note` to `notes.md` as `- <ISO time> — <note>`, commits through `commit_to_main`, and records `sync`. The sync rule, because `status.yml` cannot contain the result of its own push: write `sync: local` when the project has no `origin`, otherwise `ok`; if `commit_to_main` returns `pending`, set `sync: pending` and commit once more (that commit stays local). The next successful push carries both, and its own `status.yml` says `ok`.

`create` fields: `id` = highest id on `main` + 1, chosen **inside** the lock; `stage: intake`; `lane: null` until ②; `branch: null` until ④; `issue: null`; `checkpoints` all `pending`; `blocked: null`; `fix_rounds: 0`; `chief_session: null`; `gates: []`; `verdicts: {}`; `templates: {}`; `spend: {partial: false, by_model: {}, total_tokens: 0, weighted_tokens: 0, cost: null}`; `created` ISO seconds. `ticket.md` holds the owner's words **verbatim** under a small header (title, kind, created). `notes.md` starts with `- <time> — created at ① intake`.

- [ ] **Step 1: Failing tests** — in `tests/unit/test_tickets.py`, against a project from `scaffold.create_project` (as `test_doctor.py` builds one):
  - `test_create_writes_three_files_on_main_and_numbers_from_one`: first ticket id 1, dir `.taller/work/0001-<slug>`; `read_main` returns each file; `status.yml` parses with `stage == "intake"`, `lane is None`, all four checkpoints `pending`.
  - `test_the_owners_words_are_kept_verbatim`: words with blank lines, `>` lines and trailing spaces appear unchanged in `ticket.md`.
  - `test_reads_come_from_main_even_on_a_branch`: create ticket 1, `git checkout -b other`, create ticket 2 → id 2; `list_tickets` returns both; the working tree of `other` is untouched (`git status --porcelain` empty).
  - `test_ids_do_not_collide_across_threads`: two threads each `create` five tickets → ids 1–10, no duplicates.
  - `test_slugify` parametrized: `"Arreglar el botón"` → `arreglar-el-boton`; `"¿Qué pasa?"` → `que-pasa`; `"🙂🙂"` → `ticket`; 200 × `"a b "` → length ≤ 40, no trailing hyphen.
  - `test_a_broken_status_is_named_not_raised_from_list`: commit garbage YAML into ticket 1's `status.yml` on `main` → `list_tickets` returns ticket 2 and a problem string naming `0001`; `load(project, 1)` raises `ConfigError` whose message contains the path.
  - `test_sync_is_local_without_a_remote_and_pending_when_the_push_fails`: no origin → `sync == "local"`; with an origin that is a missing path → `sync == "pending"` in the `status.yml` on `main`.
  - `test_queue_yml_may_be_written_to_main`: `commit_to_main(project, {".taller/queue.yml": b"proposed: []\n"}, …)` succeeds.
- [ ] **Step 2: Run** `python -m pytest tests/unit/test_tickets.py -q` → fails (no module).
- [ ] **Step 3: Implement** `tickets.py` with the interfaces above; add `f"{TALLER_DIR}/queue.yml"` to `gitio.FIXED_ALLOWED`; add `| .taller/queue.yml | main | project new, ticket new --from-queue | Emptied as the queue becomes tickets (§11.4) |` to spec §7.2. `slugify`: NFKD, drop combining marks, lowercase, non-alphanumerics → `-`, collapse, strip, cut at 40 then strip `-`, `"ticket"` if empty.
- [ ] **Step 4: Run** → all pass; full suite green.
- [ ] **Step 5: Commit** `feat(tickets): tickets on main - create, read, notes, sync`

### Task 2: The stage machine

**Files:**
- Modify: `src/taller/tickets.py`, `src/taller/paths.py`
- Create: `tests/unit/test_ticket_stages.py`

**Interfaces — produces:**

```python
def next_stage(ticket: Ticket) -> str | None                  # per lane; None at close
def advance(project: Path, ticket_id: int, *, lane: str | None = None) -> Ticket
def approve(project: Path, ticket_id: int) -> Ticket          # records, then advances
def reject(project: Path, ticket_id: int, reason: str) -> Ticket
def block(project: Path, ticket_id: int, reason: str) -> Ticket
def resume(project: Path, ticket_id: int) -> tuple[Ticket, list[str]]   # (ticket, what it repaired)
def close(project: Path, ticket_id: int, *, abandon_reason: str | None = None) -> Ticket
paths.ticket_worktree(project_name: str, ticket_dir_name: str) -> Path  # ~/.taller-run/worktrees/<project>-<NNNN-slug>
```

**The rules** (each a `ConfigError` with the reason when broken):

| Move | Rule |
|---|---|
| any | refused while `blocked`, except `resume` and `close --abandon` |
| ② → next | needs `lane` (`advance(..., lane=)`), set once; on `fast`, `design` and `staging` become `skipped` |
| leaving ③ ⑦ ⑨ ⑪ | the stage's checkpoint must be `approved` — `advance` refuses and says `taller ticket approve` |
| into ④ | creates branch `ticket/NNNN-slug` from `main` and a worktree at `paths.ticket_worktree`; records `branch` |
| into ⑩ | the branch must be merged: `git merge-base --is-ancestor <branch> main`, else refused with how to merge |
| `approve` | only at ③ ⑦ ⑨ ⑪; sets that checkpoint `approved`, then advances |
| `reject` at ⑦ | §14 exactly: copy `gates/` from the worktree (if any) and the reason to `main` under `rejected/<YYYYMMDDTHHMMSS>/` (`reason.md`) **first**, then remove the worktree and delete the branch; stage `triage`; `chief_session: null`; `branch: null`; `review` back to `pending` (and `design` to `pending` on full) |
| `reject` at ③ ⑨ ⑪ | checkpoint `rejected`, and `blocked = {reason: "rejected at <stage>: <reason>", …}`; the owner resumes after acting on it |
| `block` / `resume` | `block` sets §8.4's triple; `resume` clears it **and repairs**: a ticket at or past ④ whose worktree is missing gets it recreated from its branch; a missing branch is reported, not invented |
| `close` | from `release` with `release` approved → `close`, `outcome: done`; with `abandon_reason` from any stage → `close`, `outcome: abandoned`; both remove the worktree, delete the branch if merged, and note it |

Every move calls `tickets.write(..., note=...)` naming the move (`"② triage → ④ build (lane fast)"`), so `notes.md` is the history (§7.6).

- [ ] **Step 1: Failing tests** in `test_ticket_stages.py`, one per row above, including:
  - `test_a_fast_ticket_walks_its_ten_stages`: advance/approve from ① to ⑫ with `lane="fast"`, merging the branch with `git merge` before ⑩; visited stages equal `LANE_STAGES["fast"]`; `checkpoints == {design: skipped, review: approved, staging: skipped, release: approved}`; `outcome == "done"`; worktree and branch gone.
  - `test_leaving_a_checkpoint_without_approval_is_refused` (message contains `taller ticket approve`).
  - `test_merge_is_refused_until_the_branch_is_in_main`.
  - `test_reject_at_review_keeps_the_evidence_then_cleans_up`: a `gates/tests.md` written in the worktree survives under `rejected/<ts>/` on `main` with `reason.md`; branch and worktree gone; stage `triage`.
  - `test_resume_after_a_killed_session_recreates_the_worktree` (criterion 11): ticket at ④, delete the worktree directory and `git worktree prune`, `resume` → worktree back on the branch, repair listed.
  - `test_a_blocked_ticket_keeps_its_stage`: block at ⑤ → `stage == "gates"`, `blocked.at_stage == 5`.
  - `test_the_lane_is_never_demoted` and `test_the_lane_is_set_once`.
- [ ] **Step 2: Run** → fails.
- [ ] **Step 3: Implement** the functions above in `tickets.py` and `paths.ticket_worktree`. Branch and worktree operations use `gitio.git`: `git branch <branch> main`, then `git worktree add <path> <branch>` — the ticket worktree is attached to its own branch, unlike the detached `main` worktree (§7.3).
- [ ] **Step 4: Run** → pass; full suite green.
- [ ] **Step 5: Commit** `feat(tickets): the twelve-stage machine - lanes, checkpoints, reject, resume`

### Task 3: Issue mirroring

**Files:**
- Create: `src/taller/issues.py`, `tests/unit/test_issues.py`
- Modify: `src/taller/tickets.py` (call it from `create`, `write`, `close`)

**Interfaces — produces:**

```python
def repo_of(project: Path) -> str | None            # "owner/name" from a github.com origin, else None
def open_issue(project: Path, ticket: Ticket) -> tuple[int | None, str]   # (number, reason when None)
def close_issue(project: Path, ticket: Ticket) -> str | None              # reason when it could not
```

Opened at ① with the title and the owner's words, plus `Tracked by Taller as ticket NNNN.`; closed at ⑫ with a one-line comment naming the outcome. Both through `discovery._run_gh`, so tests reuse its seam. A project with no GitHub origin is **not** a failure: `issue` stays `null` and nothing is noted. Any other failure is noted once in `notes.md` and retried by the next `tickets.write` while `issue` is `null`; the number is stored the moment it exists, so a retry can never open a second issue.

- [ ] **Step 1: Failing tests:** `test_repo_of_reads_the_origin` (https, ssh, non-GitHub → None); `test_an_issue_is_opened_at_intake_and_its_number_kept`; `test_gh_failure_leaves_the_ticket_and_retries_once_later` (first call fails, second succeeds → exactly one `issue create`, number stored); `test_no_remote_means_no_issue_and_no_noise`; `test_close_comments_and_closes`.
- [ ] **Step 2: Run** → fails. **Step 3: Implement.** **Step 4: Run** → pass, suite green.
- [ ] **Step 5: Commit** `feat(issues): mirror each ticket to a GitHub issue, surviving gh failures`

### Task 4: `taller ticket` — the commands

**Files:**
- Create: `src/taller/commands/ticket.py`, `tests/unit/test_ticket_command.py`
- Modify: `src/taller/cli.py`

**Interfaces — consumes** Tasks 1–3. **Produces** the CLI:

| Command | Does |
|---|---|
| `ticket new [words…]` | Asks, in plain words, what should be done (lines until an empty one) unless given; asks the kind (`something broken` → bug, `something new` → feature, `tidy existing code` → refactor, `a question` → question, `an idea for later` → idea); proposes a title from the first sentence (Enter keeps it). Creates, prints id, directory and issue |
| `ticket new --from-queue` | One ticket per `queue.yml` entry (kind `feature`, words = the entry), then writes `proposed: []` to `main` in the same lock; prints the ids. An empty queue says so |
| `ticket list [--all]` | Open tickets by id: `NNNN  stage  lane  title`, a `blocked` marker, problems from `list_tickets` after. `--all` includes closed |
| `ticket show <id>` | `status.yml` in plain words, what comes next and which command does it, then the last notes |
| `ticket transition <id> [--lane fast\|full]` | `advance`; at ② without `--lane` asks: *"Small and safe (a text, colour or setting in one file)? → fast. Anything else → full."* |
| `ticket approve <id>` · `ticket reject <id> [--reason]` · `ticket resume <id>` · `ticket close <id> [--abandon REASON]` | As Task 2; reject asks for the reason if not given — it goes into `notes.md` |

All accept `--path` (default: the repository you are in) and refuse an unadopted project with the `adopt` command in the message.

- [ ] **Step 1: Failing tests** with `ScriptedPrompter`, one per row, plus `test_from_queue_empties_the_queue_on_main` and `test_every_ticket_command_refuses_an_unadopted_project`.
- [ ] **Step 2: Run** → fails. **Step 3: Implement** — commands only collect input and call `tickets`/`issues`. **Step 4: Run** → pass, suite green.
- [ ] **Step 5: Commit** `feat(ticket): the ticket commands, in plain words`

### Task 5: `doctor`'s phase D row, and the proof

**Files:**
- Modify: `src/taller/doctor.py` (the D entry leaves `LATER`)
- Create: `tests/acceptance/test_ticket_lifecycle.py`
- Modify: `tests/unit/test_doctor.py`

**`doctor` check** (§15.4, phase D): per adopted project, `list_tickets` from `main` — `FAIL` on any problem (naming the file) and on any ticket with `sync: pending` (fix: *run any ticket command; the push is retried*). `local` passes.

**The proof:** empty `HOME` → `project new` (as `test_greenfield.py`) with three answers at ⑫ → `ticket new --from-queue` makes tickets 1–3 and empties the queue (criterion 4, phase D part) → ticket 1 walked ① → ⑫ on `fast` through `cli.main`, the branch merged by the test between ⑦ and ⑩ → the process is abandoned mid-ticket for ticket 2 at ④ (worktree deleted, as a killed session leaves it) and `ticket resume 2` repairs it (criterion 11, G5) → `doctor` exits 0 with the phase D check **passing**, not skipped.

- [ ] **Step 1:** Unit tests for the doctor row (broken `status.yml` fails and names it; `pending` fails; `local` passes). **Step 2:** Run → fails. **Step 3:** Implement. **Step 4:** Write the acceptance test; run it.
- [ ] **Step 5:** Full suite green; commit `test(acceptance): a queue becomes tickets; one walks to close; a killed one resumes`.

---

## Deferred, recorded rather than forgotten

| Item | Phase | Why not now |
|---|---|---|
| The chief classifying at ① and choosing the lane at ② (and the security-path refusal there) | B | Needs the chief and the explorer's file list; D asks the owner instead |
| Opening the pull request at ⑧, CI, staging deploy at ⑨ | F | GitHub wiring |
| The changelog entry at ⑫ | F | Belongs with release tooling |
| Re-laning at ④ on a diff that breaks a fast bound | B/C | Needs the diff measured by the gates |
| `chief_session` capture and reuse | B | D writes the field (`null`) and clears it on ⑦ rejection, as §7.6 says |
