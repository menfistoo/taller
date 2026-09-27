# Taller Phase B — The Chief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner states what they want once, and `taller ticket run` carries the ticket from ① to the next point that needs them — dispatching the right role on the right model, recording weighted spend, and stopping for every approval.

**Architecture:** The chief is `chief.py`: Python that owns the ticket's loop, plus one Claude conversation per ticket (`chief_session`, §7.6). Everything the spec states as a rule is decided in Python — the lane (§8.2), re-laning at ④, the budget (§7.5), fallback (§14) — and inference is used where judgement is needed: classifying the owner's words at ①, the explorer's survey at ②, the architect's plan at ③, the implementer's code at ④, the summariser at ⑦. Every dispatch goes through `inference.infer()`; its usage is folded into `status.yml` by `spend.py` under the project lock. `models.py` and `billing.py` own model availability and cost. Stages whose machinery belongs to later phases (⑤ gates and ⑥ smoke → C; ⑧ pull request and ⑨ staging deploy → F) pass through with a note; the owner's checkpoints at ③ ⑦ ⑨ ⑪ still hold.

**Tech Stack:** Python 3.11, the `claude` CLI (subscription, never `--bare`), PyYAML, pytest with the stub `claude`. No new dependency.

**Spec:** [2026-09-26-taller-design.md](../specs/2026-09-26-taller-design.md) — §10.4's Phase B row is the scope contract: *chief, routing, lanes, per-ticket sessions, model roster, `models probe`, `spend.py`, `billing.py`, `settings.py`* (settings shipped in A). Also §3.1, §3.6–§3.6.3, §5.1–§5.2, §6–§6.2, §7.5–§7.6, §8.2, §14, §15.4, §16 criteria 4 (B part), 12, 13; goals G2, G6, G7.

**Builds on:** Phases A and D on branch `phase-a/foundations` (PR menfistoo/taller#1). Their conventions hold: TDD, English code, plain-language prompts, UTF-8 at every subprocess boundary, **no real inference in tests**.

## Global Constraints

- Every act of inference goes through `inference.infer()`; nothing else spawns `claude` (§3.6). Never `--bare` (§3.6.2).
- No model name outside `model_aliases`; roles resolve `role → models[role] → model_aliases[alias]` (§5.1). `fallback: worker`.
- Ten roles, exactly: `chief architect implementer fixer gate_security gate_quality gate_ux explorer scribe summariser` (§6). Tools per role are §3.6.1's table, already in `inference.ROLE_TOOLS`.
- Only the chief holds a session; every other dispatch is one-shot, `resume: None` (§7.6). The chief's session is abandoned on a ⑦ rejection (done in D) and kept otherwise.
- The project lock is held for the whole of a chief dispatch (§7.6).
- `weighted_tokens = Σ tokens[field] × weights[field]`; `by_model` keyed by the **reported** model id; `cost` only when `billing.mode == api`; `cost_usd` of a resumed session is cumulative and never summed (§7.5).
- Budget checked at every stage transition and before any dispatch on the `thinker` alias: `per_ticket_warn` → note and continue; `per_ticket_stop` → block before dispatching (§7.5).
- Lane: `fast` needs all seven conditions of §8.2; anything else, or doubt, is `full`. A path matching `paths.security_sensitive` forces `full`, and an owner override into `fast` is refused naming the glob.
- Empty or malformed dispatch output: one retry, then block (§14). Model unavailable: fall back once per `fallback`, recorded in `status.yml` (§14).

## Review Focus

1. **A dispatch that answers, but not in the shape asked** (missing field, wrong type, prose instead of JSON) — one retry, then the ticket blocks with the reason; never a traceback, never a half-written stage. *Pinned in Task 4.*
2. **The subscription's usage window running out mid-ticket** — the failing dispatch blocks the ticket at its stage with the CLI's own message; spend already folded is kept. *Pinned in Task 4.*
3. **`taller ticket run` started twice on one ticket** (two terminals) — the second fails clearly on the project lock within 5 s and changes nothing. *Pinned in Task 4.*
4. **The implementer touching a file the explorer did not name, or a security-sensitive path, on a fast ticket** — promoted to `full`, diff kept, back to ③ with the owner told (§8.2). *Pinned in Task 4.*
5. **A `pricing` table missing the reported model id while `billing.mode == api`** — cost is computed for what is priced, `spend.partial` is set, nothing raises. *Pinned in Task 2.*

---

## File Structure

```
src/taller/
├── models.py         probe, load_probe, resolve with fallback                  (§6.2, §14)
├── billing.py        mode (configured or detected), cost, pricing staleness    (§5.2, §7.5)
├── spend.py          fold, totals, weighting, budget                            (§7.5)
├── roles.py          role definitions + answer schemas; briefing assembly       (§3.6.0, §6)
├── agents/<role>.md  nine role definitions, first line "ROLE: <role>"           (§10.1)
├── chief.py          the ticket loop: stage handlers, lane, re-lane, retries    (§7.6, §8)
├── inference.py      + the role definition ahead of the slices in --append-system-prompt
├── doctor.py         + the phase B rows
├── commands/ticket.py + `ticket run`; `ticket new` asks only the words
├── commands/models.py `taller models probe`
└── cli.py
tests/stub_claude.py  + scripted answers per role, with file effects
tests/unit/test_models.py test_billing.py test_spend.py test_roles.py test_chief.py
tests/acceptance/test_chief_run.py
```

---

### Task 1: Models and billing

**Files:** Create `src/taller/models.py`, `src/taller/billing.py`, `src/taller/commands/models.py`, `tests/unit/test_models.py`, `tests/unit/test_billing.py`. Modify `src/taller/cli.py`, `src/taller/doctor.py`, `tests/stub_claude.py` (`STUB_CLAUDE_FAIL_MODEL`: fail only when `--model` equals it).

**Interfaces — produces:**

```python
# models.py
CANDIDATES = ("opus", "sonnet", "haiku", "fable")
def probe(candidates: Iterable[str] = CANDIDATES) -> dict        # writes paths.models_probe()
def load_probe() -> dict | None                                  # {"at": iso, "models": {name: {"ok", "latency_s", "error"}}}
def reachable(model: str, probe: dict | None) -> bool | None     # None = never probed
def fallback_for(role: str, cfg: Mapping) -> str | None          # the fallback alias's model, or None if it is the same
# billing.py
def mode(cfg: Mapping) -> str                                    # configured, else detected
def mismatch(cfg: Mapping) -> str | None                         # configured differs from detected: the sentence to show
def cost(by_model: Mapping[str, Mapping[str, int]], cfg: Mapping) -> tuple[float | None, bool]   # (cost, partial)
def pricing_age_days(cfg: Mapping, today: date) -> int | None
```

`probe` makes one trivial bootstrap `infer()` per candidate with `Dispatch.model` set and `ruleset: None` (§6.2), records ok/latency/error, writes the hub file with `locking.atomic_write_text`, and never raises for a failed candidate. `cost` returns `(None, False)` unless `mode == "api"`; a model id absent from `pricing` makes `partial` true and contributes nothing (Review Focus 5). Doctor's phase B rows leave `LATER`: *every configured alias reachable per the last probe* (skip with reason when never probed, naming `taller models probe`) and *billing mode matches the environment; pricing not stale* (advisory: stale only matters on `api`).

- [ ] **Step 1: Failing tests** — `test_probe_records_each_candidate_and_survives_a_failure` (stub fails for one model via `STUB_CLAUDE_FAIL_MODEL`); `test_load_probe_is_none_before_any_probe`; `test_fallback_for_names_the_worker_model_unless_already_it`; `test_mode_prefers_configured_then_detected`; `test_mismatch_names_both`; `test_cost_is_none_off_api`; `test_cost_on_api_prices_by_reported_id` (claude-sonnet-5: 2,000,000 input → 4.00); `test_an_unpriced_model_makes_cost_partial`; `test_pricing_age`; doctor: `test_models_row_skips_until_probed_then_passes`, `test_billing_row_reports_a_mismatch`.
- [ ] **Step 2:** Run → fail. **Step 3:** Implement; add `taller models probe [--model NAME …]` printing one line per model. **Step 4:** Run → pass; full suite green.
- [ ] **Step 5: Commit** `feat(models): probe, fallback, billing mode and cost`

### Task 2: Spend

**Files:** Create `src/taller/spend.py`, `tests/unit/test_spend.py`.

**Interfaces — produces:**

```python
def weighted(by_model: Mapping[str, Mapping[str, int]], weights: Mapping[str, float]) -> int
def fold(project: Path, ticket_id: int, result: inference.Result, cfg: Mapping) -> dict   # the new spend block
def budget(ticket: Mapping, cfg: Mapping) -> str        # "ok" | "warn" | "stop"
```

`fold` takes the project lock, reloads the ticket, adds each `UsageRecord`'s four fields into `spend.by_model[record.model]`, recomputes `total_tokens`, `weighted_tokens` (rounded to int), `cost`/`partial` via `billing.cost`, and writes through `tickets.write` with **no note** (spend is not history). `cost_usd` is ignored (cumulative on a resumed session, §7.5). A `Result` with no usage but `ok` sets `partial: true` — spend is never estimated.

- [ ] **Step 1: Failing tests** — `test_weighted_matches_the_spec_example` (§7.1: haiku 1,200/9,000/31,000/3,100 + sonnet 2,400/22,000/64,000/12,600 → **130,350**); `test_fold_accumulates_by_reported_model_across_dispatches`; `test_cost_usd_is_never_summed` (two folds of a resumed session with cumulative `cost_usd` 0.5 then 0.9 leave `cost` driven by usage only); `test_no_usage_marks_partial`; `test_budget_thresholds` (below warn / at warn / at stop, using `budget.per_ticket_warn` 400,000 and `per_ticket_stop` 1,200,000); Review Focus 5 lives in Task 1's `test_an_unpriced_model_makes_cost_partial` and is folded here in `test_fold_on_api_with_an_unpriced_model_is_partial`.
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(spend): fold per-dispatch usage into the ticket, weighted, with a budget`

### Task 3: Roles — definitions, answer shapes, briefing

**Files:** Create `src/taller/roles.py`, `src/taller/agents/{chief,architect,implementer,fixer,gate_security,gate_quality,gate_ux,explorer,scribe,summariser}.md` (ten; the spec's "nine agents" plus the chief's own brief, since the CLI chief is dispatched too), `tests/unit/test_roles.py`. Modify `src/taller/inference.py` (`_brief`), `pyproject.toml` package data if needed.

**Interfaces — produces:**

```python
ROLES: tuple[str, ...]                                   # the ten, §6
def definition(role: str) -> str                         # agents/<role>.md; first line "ROLE: <role>"
SCHEMAS: dict[str, dict]                                  # JSON Schema per role that answers in structure
def check(role: str, value: Any) -> str | None            # None when valid, else what is wrong
```

Answer shapes (the whole contract between chief and roles):

| Role | Schema (required keys) |
|---|---|
| `chief` at ① | `kind` (one of `KINDS`), `title` (≤ 120), `summary` |
| `explorer` at ② | `files` (list of paths to change), `adds_or_deletes_files`, `schema_change`, `route_change`, `dependency_change` (bools), `change_kind` (`literal` `string` `style` `threshold` `other`), `notes` |
| `architect` at ③ | `plan_md` (the plan, Markdown) |
| `implementer` at ④ | `summary`, `commits` (list of shas it made) |
| `summariser` at ⑦ | `summary_md` |

`inference._brief` becomes: the role's definition, then its slices (§3.6.0), then any `Dispatch.system` addendum. **The first line of every brief is `ROLE: <role>`** — it is how the test stub answers per role, and it survives the Windows `.cmd` shim, which truncates multi-line arguments after the first line (see `tests/conftest.py`). Each definition says: who it is, what it may touch, what it must answer, in plain English, generic (no project or owner knowledge — G9, the vocabulary test covers `agents/`).

- [ ] **Step 1: Failing tests** — `test_every_role_has_a_definition_starting_with_its_marker`; `test_the_brief_is_definition_then_slices` (`_brief` for `gate_ux` starts `ROLE: gate_ux` and contains the `ux` slice but not `security`); `test_check_accepts_a_good_answer_and_names_what_is_wrong` (per schema: missing key, wrong type, unknown enum); `test_definitions_ship_in_the_wheel` (package data).
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green (existing inference tests asserting the brief may need the new prefix — rule and ledger).
- [ ] **Step 5: Commit** `feat(roles): role definitions and answer shapes; briefs lead with the role`

### Task 4: The chief — `taller ticket run`

**Files:** Create `src/taller/chief.py`, `tests/unit/test_chief.py`. Modify `tests/stub_claude.py`, `src/taller/commands/ticket.py`, `src/taller/cli.py`, and spec §8.1 (a note that the full lane's branch exists from ③ — see the ③ row). The chief moves tickets with Phase D's `advance`/`block`; `tickets.py` is not changed.

**Interfaces — consumes** Tasks 1–3 and Phase D's `tickets.advance/approve/block/load/write`. **Produces:**

```python
def classify(project: Path, ticket_id: int) -> Ticket          # ① chief dispatch, starts chief_session
def run(project: Path, ticket_id: int, *, lane: str | None = None,
        say: Callable[[str], None] = print) -> Ticket          # until a checkpoint, merge, block or close
def decide_lane(facts: Mapping, ruleset: Mapping) -> tuple[str, str]          # (lane, reason) — §8.2
def needs_promotion(diff: Mapping, ticket: Mapping, ruleset: Mapping) -> str | None   # reason, §8.2 ④
```

**The loop.** `run` takes the project lock for its whole duration (§7.6) and repeats: check the budget (`stop` → block); dispatch the stage's handler; fold its usage; advance — until the ticket reaches a checkpoint awaiting approval, ⑩ with the branch unmerged, a block, or ⑫.

| Stage | Handler |
|---|---|
| ① intake | `classify` when the kind is not yet the chief's: chief dispatch (new session) → kind/title/summary; `chief_session` stored; words untouched |
| ② triage | `generated.refresh` (§4.6's ② trigger); explorer dispatch, cwd the `main` worktree refreshed to `main` (read-only role); `decide_lane`; an owner `--lane fast` refused when a security glob matches, naming it; files named in `notes.md` |
| ③ design | worktree + branch opened here for `full` (ruling: §7.2 puts `plan.md` on the branch at ③, before §8.1's ④ — the spec's own two tables disagree; the branch exists from ③ on the full lane); architect dispatch writes `plan.md` in the ticket folder on the branch and commits; stop at checkpoint 1 |
| ④ build | implementer dispatch, cwd the worktree, `writable` the worktree; then `needs_promotion` on `git diff main...branch --numstat` (§8.2: > `max_fast_lane_lines`, a file added/deleted, a second file, a security path) → `lane: full`, `design: pending`, back to ③ with the diff kept, owner told |
| ⑤ gates · ⑥ smoke | pass through, noted *"gates arrive in phase C"* |
| ⑦ review | summariser dispatch → `review.md` in the ticket folder on the branch; stop at checkpoint 2 |
| ⑧ pr | pass through, noted *"the pull request arrives in phase F; merge the branch yourself"* |
| ⑨ staging | checkpoint 3 on `full` (approval without a deploy until F) |
| ⑩ merge | stop until merged (D's rule) |
| ⑪ release | checkpoint 4 |

**Failures** (§14): a `Result` not ok, or an answer failing `roles.check`, is retried **once**; the second failure blocks the ticket with the reason (Review Focus 1 and 2). A model-unavailable error falls back once to `models.fallback_for(role)` and records `{role, requested, used}` under `status.fallbacks`. A thinker-alias dispatch checks the budget first.

`ticket new` in phase B asks only the owner's words (G2) and runs `classify`; `--kind` keeps D's manual path. `taller ticket run <id> [--lane fast|full]` prints each stage as it passes and ends with `next_hint`.

**Stub:** `STUB_CLAUDE_SCRIPT` names a JSON file `{role: [answer, …]}`; the stub reads the role from the `ROLE:` line of `--append-system-prompt`, pops the next answer, and returns it as `structured_output` with fixed usage (model `claude-sonnet-5`, 100/0/0/50). An answer may carry `"effects": [{"write": path, "text": …}, {"commit": message}]`, applied in its cwd — how the implementer "writes code" in tests — and `"fail": "text"` to return `is_error`.

- [ ] **Step 1: Failing tests** in `test_chief.py`: `test_new_asks_only_the_words_and_the_chief_classifies`; `test_decide_lane` parametrized over §8.2's seven conditions plus the security precedence; `test_an_owner_fast_override_on_a_security_path_is_refused_naming_the_glob`; `test_a_fast_run_stops_at_review_with_spend_recorded`; `test_a_full_run_stops_at_design_with_the_plan_on_the_branch`; `test_promotion_at_build_keeps_the_diff_and_returns_to_design` (Review Focus 4); `test_a_malformed_answer_is_retried_once_then_blocks` (Review Focus 1); `test_an_exhausted_window_blocks_with_the_cli_message` (Review Focus 2); `test_a_second_run_on_the_same_ticket_fails_on_the_lock` (Review Focus 3); `test_the_chief_session_is_kept_across_stages` (the second chief dispatch passes `--resume <id>`); `test_budget_stop_blocks_before_a_thinker_dispatch`; `test_an_unavailable_model_falls_back_and_is_recorded`.
- [ ] **Step 2:** Run → fail. **Step 3:** Implement stub scripting, then `chief.py`, then the commands. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(chief): taller ticket run - the ticket loop, lanes, retries, spend`

### Task 5: The proof

**Files:** Create `tests/acceptance/test_chief_run.py`.

Empty `HOME` → `project new` → `ticket new "…"` (the chief classifies) → `ticket run` stops at ⑦ review (fast lane, explorer names one template, implementer writes it) → `ticket approve` → `ticket run` passes ⑧ and stops at ⑩ → the test merges the branch → `ticket run` stops at ⑪ → `ticket approve` → closed. Assert: **criterion 4 (B part)** — a ticket ran ① → ⑩ end to end; **criterion 12** — `spend.weighted_tokens > 0` with `by_model` keyed by the reported id; **criterion 13** — the run never passed ⑦ or ⑪ without an approval; `doctor` exits 0 with the phase B rows passing after `taller models probe`.

- [ ] Write · run · full suite green · commit `test(acceptance): one ticket, stated once, run from intake to merge`

---

## Deferred, recorded rather than forgotten

| Item | Where | Why not now |
|---|---|---|
| The Claude Code plugin — slash commands (`/taller:new` …), the `SessionStart` hook, and `spend.py`'s transcript fallback for in-session work | its own phase after C | A second front end over this same library; useful once gates exist, and its spend path only matters there |
| Gates at ⑤, smoke at ⑥, the fixer's rounds | C | Pass through in B |
| Pull request at ⑧, staging deploy at ⑨ | F | Pass through in B; checkpoint 3 still asks the owner |
| "Two tickets touch the same files" warning at ② (§14) | C | Needs the gates' diff view; noted as a limit |
