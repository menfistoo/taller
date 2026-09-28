# Taller Phase C — Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every change is checked before the owner sees it — mechanically where a rule is decidable, by a model where it takes judgement — and a finding is fixed, run as a command, or put in front of the owner according to its rule, never argued away.

**Architecture:** A `gates/` package. Each Python gate is a pure function `run(diff, ruleset) -> Verdict` (and `scan(tree, ruleset)` for the whole tree), over a `Diff` built once from git (§10.2). The three LLM gates are one module dispatching `gate_security`/`gate_quality`/`gate_ux` with a findings schema. `gates/__init__.py` owns the §9.7 rule table (severity + remediation), the §9.2 selection, the §7.4 verdict file, and routing. The chief's ⑤ and ⑥ stop passing through: they select, run (in parallel up to `max_parallel_gates`), apply overrides, write `gates/<name>.md` on the branch, fold counts into `status.yml`, and route — `agent` → the fixer (max `max_fix_rounds`, never a test file), `command` → the deterministic command, `escalate` → block with the reason.

**Tech Stack:** Python 3.11 (`ast` for function lengths and imports), `pytest` run as a subprocess, `urllib` for smoke HTTP, the stub `claude` for LLM gates in tests. No new dependency.

**Spec:** [2026-09-26-taller-design.md](../specs/2026-09-26-taller-design.md) — §10.4's Phase C row is the scope contract: *gates — constitution first, then size/tests/smoke, then the three LLM gates; `scan()` mode; `project adopt` removes the superseded `code-review/`, `security-review/`, `design-review/` directories.* Also §7.4, §8.2 (new-ui-literal), §9.1–§9.8, §4.5, §4.6, §14, §15.1–§15.3, §16 criteria 3, 10, 14, 15; goal G4.

**Builds on:** Phases A, D, B on `phase-a/foundations`. Conventions hold: TDD, plain-language messages, UTF-8 at every subprocess boundary, the stub `claude` in every test.

## Global Constraints

- Finding = `{gate, severity, rule, file, line, message, fix_hint, overridden}`; severities `BLOCKER HIGH MEDIUM LOW NIT` (§7.4).
- Verdict file `gates/<name>.md`: YAML front matter `gate, result (pass|fail|error), hub_sha, ran_at, counts{blocker,high,medium,low,nit}, metrics, findings`, then prose (§7.4). `result: error` counts as BLOCKER, never a pass.
- The §9.7 table is the only source of severity and remediation for Python-gate rules; LLM gates declare theirs per finding; every `security.*` rule is non-suppressible (§4.5).
- Selection (§9.2): always constitution, size; tests when any `.py` changed or tests exist; ux when a path matches `paths.ui` **and** lane is full; quality when lane is full; security when a path matches `paths.security_sensitive`. Smoke only at ⑥.
- Severity policy (§9.3): BLOCKER/HIGH act per remediation; MEDIUM goes to the owner's summary, never auto-fixed; LOW/NIT logged.
- The fixer never modifies a test file — enforced by `Dispatch.forbidden` (already in `inference`), asserted on argv; a round whose diff touches one aborts and escalates.
- Thresholds from the ruleset: `max_file_lines 800`, `max_function_lines 80`, `dup_block_lines 12`, `max_fix_rounds 2`, `min_coverage_pct 0`.
- Smoke: HTTP 200 **with a non-empty body** on every route; an allocated ephemeral port; `data: copy` never opens the live DB or its `-wal`/`-shm`; the subprocess tree ended in a `finally` (§9.6).
- Security globs matched with `globs.match` (phase B), never `fnmatch`.

## Review Focus

1. **A gate that cannot run** (pytest not installed in the worktree's interpreter, the app's dependencies missing, a syntax error in a changed file) — `result: error` → BLOCKER → escalate with the gate's own output, never a pass and never a fixer round. *Pinned in Tasks 3 and 4.*
2. **A changed file that is not Python or not UTF-8** (a PNG, a minified bundle, a Latin-1 CSV) — the gates skip what they cannot read with a note, never crash. *Pinned in Task 1 (`Diff`).*
3. **The fixer "fixing" a failing test by editing it** — the harness denies the write; if the round's diff still touches a test path, the round aborts and escalates. *Pinned in Task 6.*
4. **Two tickets smoke-testing at once** — distinct ports, distinct data copies, neither touching the owner's running dev server on 5000. *Pinned in Task 4.*
5. **A hex colour that is legitimately not a brand value** (a colour inside the generated `tokens.css`, a hex in a Python test fixture, `#` anchors like `href="#top"`) — only brand-shaped literals in style-bearing files are flagged, and the generated tokens path is exempt. *Pinned in Task 2.*

---

## File Structure

```
src/taller/gates/
├── __init__.py      Finding, Verdict, RULES (§9.7), select (§9.2), route, render/parse verdict (§7.4)
├── diff.py          Diff from git (base, head, commits, files{path,status,added,removed,content})
├── constitution.py  run + scan: brand, layers, root md, single-use scripts, commit shape,
│                    new UI literals, snapshot stale/modified, override problems
├── size.py          run + scan: file length, function length (ast), duplicate blocks
├── tests.py         run + scan: pytest subprocess, outcome, metrics, coverage when asked
├── smoke.py         http / import / none; port, data copy, auth basic, mapped routes
└── llm.py           security / quality / ux via inference; findings schema; dry-run
src/taller/chief.py            ⑤ and ⑥ run the gates; fixer rounds; routing; templates map
src/taller/commands/scan.py    `taller scan [path] [--all]`
src/taller/adopt.py            proposes and removes superseded review directories
src/taller/doctor.py           phase C row
src/taller/catalogue/…         flask-sqlite: run_local.py honours $PORT; smoke boots on the allocated port
tests/fixtures/broken-app/     §15.2
tests/unit/test_gates_*.py  tests/unit/test_golden.py  tests/acceptance/test_gated_run.py
```

---

### Task 1: The gate core

**Files:** Create `src/taller/gates/__init__.py`, `src/taller/gates/diff.py`, `tests/unit/test_gates_core.py`.

**Interfaces — produces:**

```python
Finding = dict   # §7.4
Verdict = {"gate": str, "result": "pass"|"fail"|"error", "findings": [Finding], "metrics": dict}
RULES: dict[str, tuple[str, str | None]]         # rule -> (severity, remediation) — §9.7 verbatim
def finding(rule, file="", line=0, message="", fix_hint=None, *, gate=None) -> Finding   # severity from RULES
def select(ticket: Mapping, diff: Diff, ruleset: Mapping) -> list[str]                    # §9.2, stable order
def route(findings: list[Finding]) -> dict[str, list[Finding]]   # keys: agent, command, escalate, summary, log
def counts(findings) -> dict[str, int]
def render_verdict(verdict: Verdict, *, hub_sha: str, prose: str) -> bytes
def parse_verdict(text: str) -> Verdict
# diff.py
Diff = {"base", "head", "commits": [{"sha","message"}],
        "files": [{"path","status","added":[{"line","text"}],"removed":[...],"content": str|None}]}
def build(repo: Path, base: str, head: str) -> Diff       # base...head, ticket files excluded
def tree(repo: Path) -> Diff                              # every tracked file as "added" - for scan()
```

`route`: an unsuppressed BLOCKER/HIGH goes to its rule's remediation (`agent`/`command`/`escalate`); LLM-gate findings carry their own `remediation`; a finding with `overridden` set is already NIT and goes to `log`; MEDIUM → `summary`; LOW/NIT → `log`. `result: error` verdicts become one `escalate` entry. `diff.build` reads each file's text as UTF-8 and sets `content: None` (with the path still listed) when a file is binary or undecodable — Review Focus 2.

- [ ] **Step 1: Failing tests** — `test_rules_match_the_spec_table` (every §9.7 row, e.g. `RULES["smoke.not-rendered"] == ("HIGH", "escalate")`, `RULES["constitution.new-ui-literal"] == ("MEDIUM", None)`, and `set(RULES) == overrides.DECLARED_RULE_IDS`); `test_select` parametrized over §9.2's five rows incl. the fast-lane ux exclusion; `test_route_sends_each_finding_where_its_rule_says`; `test_an_overridden_blocker_is_only_logged`; `test_verdict_round_trips` (render → parse, LF, counts); `test_diff_lists_added_and_removed_lines_with_numbers`; `test_diff_survives_a_binary_and_a_latin1_file`; `test_diff_excludes_ticket_files`.
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(gates): the rule table, selection, routing and verdict files`

### Task 2: The constitution gate, and the broken-app fixture

**Files:** Create `src/taller/gates/constitution.py`, `tests/fixtures/broken-app/…` (§15.2), `tests/unit/test_gates_constitution.py`.

**Interfaces:** `run(diff, ruleset) -> Verdict`, `scan(tree_diff, ruleset) -> Verdict`.

| Rule | Decidable test |
|---|---|
| `brand.hardcoded-color` | an added line in a `.css`/`.scss`/`.html`/`.j2`/`.js`/`.vue` file containing `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb(`/`rgba(`/`hsl(` — **not** in `paths.brand_tokens`, not inside `var(--…, <fallback>)`, not an `href="#…"`/`id` anchor; one finding per literal (Review Focus 5) |
| `brand.hardcoded-font` | an added `font-family:` whose value is not wholly `var(--…)` / `inherit` / `initial` / `unset`, outside `paths.brand_tokens` |
| `constitution.layer-violation` | a changed `.py` matching a `paths.layers` key imports (via `ast`) a local top-level module not in that key's allowed list (`utils.*` style globs allowed) |
| `constitution.root-markdown` | an **added** root `.md` other than README/CLAUDE/CHANGELOG/LICENSE |
| `constitution.single-use-script` | an **added** root `fix_*.py`, `check_*.py`, `debug_*.py`, `diagnose_*.py`, `_*.py`, or `test_*.py` outside `tests_dir` |
| `constitution.commit-message-shape` | a commit subject not matching `^(feat|fix|refactor|chore|docs|test|perf)(\([a-z0-9-]+\))?: .{1,72}$` |
| `constitution.new-ui-literal` | when `language.ui` is set and not `none`: in a changed template, an added text node or `placeholder`/`title`/`aria-label`/`alt` attribute with letters in it (Jinja `{{ }}`/`{% %}` stripped) |
| `constitution.resolved-snapshot-modified` | the diff touches `.taller/resolved.json` or `00-index.md` (a branch must not carry them, §4.6) |
| `constitution.resolved-snapshot-stale` | the snapshot on `main` records a `hub_sha` other than the ruleset's |
| `constitution.override-*`, `unknown-rule-id` | `overrides.apply([], ruleset)` output, carried through |

`scan` applies the same rules to `diff.tree(repo)` (every file as added; no commits). The fixture `tests/fixtures/broken-app/` is built per §15.2 as files on disk, and a test helper turns it into a git repo with a violating commit on a branch.

- [ ] **Step 1: Failing tests** — `test_broken_app_violations_caught_by_id_and_severity`, parametrized over each constitution-owned violation of §15.2 with its §9.7 severity; `test_the_generated_tokens_path_is_exempt`; `test_fallbacks_anchors_and_python_hexes_are_not_colours` (Review Focus 5); `test_new_ui_literal_only_when_language_ui_is_set`; `test_commit_shape_accepts_the_conventional_form`; `test_scan_counts_pre_existing_violations`.
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(gates): the constitution gate, mechanical and exact`

### Task 3: Size and tests

**Files:** Create `src/taller/gates/size.py`, `src/taller/gates/tests.py`, `tests/unit/test_gates_size_tests.py`.

- **size** — `size.file-too-long` (a changed file whose line count exceeds `max_file_lines`), `size.function-too-long` (a Python function or method, by `ast` `end_lineno - lineno + 1`, over `max_function_lines`, **in a changed region**), `size.duplicate-block` (§9.1's normalisation; a window of `dup_block_lines` normalised lines identical to another window anywhere in the tree, one side containing an added line). `scan` over the whole tree. Metrics: `files_checked`, `longest_function`.
- **tests** — `python -m pytest -q -p no:cacheprovider` in the worktree with `timeout = 600`, the tree of `sys.executable` unless the project has `venv/` or `.venv/` (then that interpreter). Exit 0 → pass; 1 → `tests.failed` per failing test id (parsed from the `-rf` summary); 5 (none collected) → pass with `tests_run: 0`; any other exit, a timeout, or no interpreter → `result: error` + `tests.error` carrying the output tail (Review Focus 1). Coverage only when `min_coverage_pct > 0` and `pytest-cov` importable, adding `--cov`; below the minimum → `tests.coverage-below-minimum` (MEDIUM, escalate — in `RULES` from Task 1, per §9.7's closing paragraph). Metrics: `tests_run`, `tests_passed`, `duration_s`, `coverage_pct` when measured.

- [ ] **Step 1: Failing tests** — `test_a_long_function_in_the_change_is_flagged_and_an_untouched_one_is_not`; `test_a_file_over_the_limit`; `test_duplicate_blocks_by_the_normalisation`; `test_passing_suite_passes_with_metrics`; `test_a_failing_test_is_named`; `test_no_tests_is_a_pass_with_zero`; `test_a_suite_that_cannot_run_is_an_error_not_a_pass` (syntax error in conftest); plus broken-app rows for size.
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(gates): size and tests`

### Task 4: Smoke

**Files:** Create `src/taller/gates/smoke.py`, `tests/unit/test_gates_smoke.py`. Modify the flask-sqlite scaffold (`run_local.py` reads `PORT`), the three catalogue profiles' `smoke` blocks (flask: `boot: "python run_local.py"`, `ready: auto`, `env: {PORT: "$TALLER_SMOKE_PORT", DATABASE: "$TALLER_SMOKE_DATA/app.db"}`, `data: copy`; static-site already `ready: auto`), and spec §4.1's example.

**Interfaces:** `run(worktree: Path, ruleset, *, templates: Mapping[str, list[str]] | None) -> Verdict`.

Behaviour exactly §9.6: allocate a free port (`socket.bind(("127.0.0.1", 0))`); `$TALLER_SMOKE_PORT`, `$TALLER_SMOKE_DATA`, `$TALLER_SMOKE_SECRET` substituted into `boot`, `ready`, `env`; `data: copy` copies the project database (the file `env.DATABASE`/`DATABASE_PATH` names, resolved against the project, **without** its `-wal`/`-shm`) into a temp dir, `fresh` leaves it empty, `none` skips; boot with `inference._kill_tree` in a `finally`; poll `ready` until 200 or `timeout_s` → `smoke.timeout`; the process exiting first → `smoke.boot-failed` with its stderr tail; GET `routes` plus the routes of changed templates from `templates`, a changed template with no mapping → `smoke.unmapped-template`; 5xx or connection error → `smoke.route-error`; 3xx without `auth` → `smoke.not-rendered`; 200 with an empty body → `smoke.not-rendered`; `auth: basic` sends the header and follows redirects. `import`: `python -c "import <module>"` in a subprocess with the timeout. `none`: pass with `skipped: true`.

- [ ] **Step 1: Failing tests** (§15.1's list, against tiny throwaway apps written by the test — a stdlib `http.server` script whose behaviour is chosen by an env var): `test_a_healthy_app_passes_on_an_allocated_port`; `test_boot_failure`; `test_a_500_is_a_route_error`; `test_a_302_to_login_is_not_rendered`; `test_an_empty_200_is_not_rendered`; `test_timeout_reaps_the_process_tree`; `test_two_runs_get_distinct_ports` (Review Focus 4); `test_data_copy_never_touches_the_source_db_or_its_wal`; `test_import_kind_raising`; `test_none_kind_passes_skipped`; `test_an_unmapped_template_is_medium`; `test_the_generated_flask_project_boots` (criterion 3: `scaffold.create_project` then smoke on its checkout).
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(gates): smoke - the app boots and the change renders`

### Task 5: The three LLM gates, and doctor's phase C row

**Files:** Create `src/taller/gates/llm.py`, `tests/unit/test_gates_llm.py`. Modify `src/taller/roles.py` (a `findings` schema for the three gate roles), `src/taller/agents/gate_*.md` (the rule-id guidance), `src/taller/doctor.py`.

**Interfaces:** `run(gate: str, project: Path, ticket: Mapping, diff_text: str, ruleset, cfg) -> tuple[Verdict, inference.Result]`; `dry_run(gate, ruleset, cfg) -> str | None` (the problem, or None).

Findings schema: `findings: [{rule, severity, file, line, message, fix_hint, remediation}]`, `rule` must start with the gate's domain (`security.`, `quality.`, `ux.`) and `remediation` be `agent` or `escalate`; a malformed finding is dropped with a note (not a crash), and an unusable answer twice is `result: error`. The gate is dispatched one-shot (no `resume`) with `cwd` the worktree, the diff in the prompt, and its role's slices. The UX gate's prompt names `language.ui`. `dry_run` builds the dispatch without calling `infer` and checks the model is reachable per the probe — doctor's C row (§15.4): *every Python gate executes (on an empty diff); smoke configuration valid for the profile; `smoke.auth.secret` resolvable if declared; each LLM gate dry-runs*.

- [ ] **Step 1: Failing tests** — `test_a_security_finding_comes_back_as_a_finding`; `test_a_finding_outside_the_gates_domain_is_dropped_with_a_note`; `test_an_unusable_answer_twice_is_an_error_verdict`; `test_the_ux_gate_is_told_the_ui_language`; `test_security_findings_cannot_be_suppressed` (an override for a `security.*` id is refused — §4.5, via `overrides.apply`); doctor: `test_phase_c_row_passes_on_a_created_project`, `test_an_unset_smoke_secret_is_reported`.
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(gates): security, quality and ux by model; doctor's phase C row`

### Task 6: The chief runs the gates — ⑤, ⑥, the fixer

**Files:** Modify `src/taller/chief.py`, `src/taller/roles.py` (explorer answer gains optional `templates`), `tests/stub_claude.py` (if needed). Create `tests/unit/test_chief_gates.py`.

**Behaviour:**
- ② stores the explorer's optional `templates` map into `status.templates` (§9.6).
- ⑤: `diff.build(project, main, branch)`; `select`; run the selected gates — Python ones in a thread pool of `concurrency.max_parallel_gates`, LLM ones through `llm.run` (their `infer` already takes pool slots); `overrides.apply` to each verdict's findings; write every `gates/<name>.md` into the worktree and commit them in one `chore(gates): …` commit (branch side, §7.2); `status.gates` (every gate that ran) and `status.verdicts` (§7.1 shape with `hub_sha`); then `route`: `command` findings run their command (`constitution.resolved-snapshot-stale` → `generated.refresh`) and the gates re-run once; `escalate` → block with every escalated finding's message; `agent` → a fixer round (below) while `fix_rounds < max_fix_rounds`, else block ("survived N fix rounds", §14); nothing actionable → advance, MEDIUM findings noted for ⑦.
- The fixer round: dispatch `fixer` (one-shot, cwd and writable the worktree, `forbidden` from `inference.role_forbidden`) with the actionable findings; commit leftovers as the implementer's are; **if the round's diff touches `tests_dir/**`, `**/test_*.py` or `**/*_test.py`, revert the round's commits and escalate** (Review Focus 3); `fix_rounds += 1`; re-run ⑤.
- ⑥: `smoke.run(worktree, ruleset, templates=status.templates)`; verdict written like ⑤'s; `smoke.route-error` → a fixer round under the same cap; the rest escalate per §9.7.
- ⑦: the summariser's prompt gains the verdict counts and every MEDIUM finding; the chief compares each verdict's `hub_sha` with the current one and notes when rules moved under the ticket (§14).

- [ ] **Step 1: Failing tests** (stub scripts for implementer/fixer/gates): `test_a_clean_fast_change_passes_three_gates_and_smoke`; `test_a_hardcoded_colour_is_fixed_by_the_fixer_in_one_round`; `test_a_finding_that_survives_two_rounds_blocks`; `test_an_escalated_finding_blocks_without_a_fixer` (§15.1 remediation routing: `tests.error`, `smoke.boot-failed`, `smoke.not-rendered`, `size.file-too-long`); `test_a_stale_snapshot_runs_taller_resolve_then_passes`; `test_a_fixer_round_touching_a_test_is_reverted_and_escalated`; `test_verdict_files_land_on_the_branch_and_counts_in_status`; `test_medium_findings_reach_the_review_summary`; `test_rules_moving_mid_ticket_are_noted_at_review`.
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(chief): gates at 5, smoke at 6, fixer rounds by rule`

### Task 7: `taller scan`, and adoption drops superseded review directories

**Files:** Create `src/taller/commands/scan.py`, `tests/unit/test_scan.py`. Modify `src/taller/cli.py`, `src/taller/adopt.py`, `src/taller/commands/project.py`, `tests/unit/test_adopt.py`.

- `taller scan [path] [--all]` runs every Python gate's `scan` (smoke exempt, §9.5) and prints per project: counts by severity, the top rules, and the tests metrics — the Health figures (§12, criterion 15). Writes nothing.
- Adoption: the brief lists found `code-review/`, `security-review/`, `design-review/` as *"replaced by Taller's gates — removed in the adoption commit"*, with a brief choice to keep them; approved → `git rm -r` in the adoption commit (criterion 10).

- [ ] **Step 1: Failing tests** — `test_scan_reports_the_broken_apps_violations_by_severity`; `test_scan_all_covers_every_adopted_project`; `test_scan_writes_nothing`; `test_adoption_removes_superseded_review_dirs`; `test_the_owner_can_keep_them`.
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(scan): health figures per project; adoption retires old review dirs`

### Task 8: The proof — §15.2, §15.3, criteria 3 and 14

**Files:** Create `tests/unit/test_golden.py`, `tests/acceptance/test_gated_run.py`.

- **§15.2** every violation in `broken-app` caught by its gate, **by rule id and §9.7 severity**, in one parametrized test (the UX string and the missing `@permission_required` are LLM-gate rows, asserted through a scripted gate answer; the rest are mechanical).
- **§15.3 golden tickets**: twelve synthetic requests (explorer facts + resulting diff) with expected lane, promotion and gate selection — including the four the spec names (promoted on size; promoted on a newly touched security path; forced `fast` over a security path refused; a fast ticket where `ux` is not selected despite `paths.ui` and `new-ui-literal` fires instead).
- **Acceptance**: empty HOME → `project new` (flask) → a ticket whose implementer introduces a hardcoded colour → ⑤ flags `brand.hardcoded-color`, the fixer replaces it with the token → gates pass → ⑥ boots the real generated app and GETs `/` (criterion 3) → ⑦ … ⑫ → the merged `main` has no unsuppressed `brand.hardcoded-*` (criterion 14); `doctor` green with the phase C row passing.

- [ ] Write · run · suite green · commit `test(acceptance): a gated ticket - flagged, fixed, booted, merged clean`

---

## Deferred, recorded rather than forgotten

| Item | Where | Why not now |
|---|---|---|
| `taller-ci.yml` running the three model-free gates in CI (§9.4) | F | GitHub wiring |
| Cockpit Health screen | E | `taller scan` produces the figures now |
| Golden tickets from *recorded real* requests (§15.3) | when real tickets exist | none recorded yet; synthetic cases pin the same decisions |
| The two-tickets-touch-the-same-files warning at ② (§14) | stays deferred | needs a cross-ticket index; out of this plan's scope |
