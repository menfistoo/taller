# Taller Phase F — GitHub and staging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Work leaves the owner's machine safely: every push to one of her projects is re-checked on GitHub by the three gates that need no model, a ticket reaching ⑧ becomes a pull request that carries its own evidence, and a `full` ticket can be seen running on staging before she releases it.

**Architecture:** One new CLI entry point, `taller ci`, runs the model-free gates against the committed `.taller/resolved.json` — no hub, no secrets, no model — and prints GitHub annotations. A workflow file shipped in every scaffold calls it twice, as two jobs, so the required check always reports. `prs.py` turns a ticket and its verdicts into a pull request body; the chief's ⑧ creates it with `gh`. `taller stage` wraps `docker compose` for a `full` ticket's staging run. Nothing here changes a setting on her GitHub account: `taller github protect` prints the rule to turn on and `doctor` reports when it is off.

**Tech Stack:** Python 3.11, `gh` as a subprocess (as `issues.py` already does), GitHub Actions, `docker compose` as a subprocess, a stub `docker` and stub `gh` in tests. No new dependency.

**Spec:** [2026-09-26-taller-design.md](../specs/2026-09-26-taller-design.md) — §10.4's Phase F row is the scope contract: *GitHub wiring, `taller-ci.yml`, branch ruleset, staging environment.* Also §9.4 (two jobs, two check names, the required check always reports), §13 (the table: workflow, pull request template, branch protection, issue ↔ ticket), §13.1 (`taller stage`, and why it is not a CI job), §13.2 (remotes stay local-only until she says otherwise), §4.6 (CI loads the snapshot, never resolves), §15.4's F row, §15.6, criteria 16, 17, 18.

**Builds on:** Phases A, D, B, C and the plugin, merged on `phase-a/foundations` (834 tests) and pushed. Conventions hold: TDD, plain-language messages, UTF-8 at every subprocess boundary, no real `claude` and no real network in tests.

## The owner's decisions (2026-09-29)

- **The Taller repository becomes public**, so CI installs it with `pip` and needs no key and no secret (§9.4's "no secrets"). Task 1 makes that safe first: the owner's word list moves to her hub, the repository keeps a short made-up example, and the spec's owner line goes. Her name and email stay on the commits, as on any public repository. **Making it public is her action, not a task here** — after Task 1, `gh repo edit <account>/taller --visibility public`.
- **Taller never changes a GitHub repository setting.** It prints the exact rule to turn on; `doctor` reports when it is off (Task 5).

## Global Constraints

- CI runs **only** constitution, size and `pytest`, against `.taller/resolved.json` (`constitution.load_snapshot`, `mode: "ci"`), never resolving, with no hub and no `ANTHROPIC_API_KEY` (§9.4).
- The workflow has **no workflow-level `paths-ignore`** and the `gates` job **always reports a conclusion**: a required check that never reports leaves a pull request pending for ever (§9.4).
- Two check names: `taller-ci` (job `gates`, the required one) and `taller-ci-mode` (job `mode`, informational, prints `full` or `ticket-files`) (§9.4).
- A push touching only `.taller/work/**` is `ticket-files`: the `gates` job exits 0 at once (§9.4).
- `taller stage` runs on the deployment host, never in CI: GitHub Actions cannot reach a Tailscale-only server (§13.1).
- Staging is separate in every way: its own compose project name `<project>-staging`, its own port, and `./data-staging/` holding a **copy** of the production database — the live file and its `-wal`/`-shm` are never opened (§13.1, §9.6's care).
- No remote is created for the hub or for Taller itself without her explicit instruction (§13.2).
- Every message a person reads is plain language: what happened, and the one command that deals with it.

## Review Focus

1. **A project with no GitHub remote** — most of hers. ⑧ must say so and let her merge locally, exactly as it does today; it must not stall or fail. *Pinned in Task 4.*
2. **`gh` missing, signed out, or without the `workflow` scope** — adopt still writes the workflow file, and ⑧ reports the reason in one line rather than a traceback. *Pinned in Tasks 3 and 4.*
3. **CI on a checkout that cannot see the base commit** (a shallow clone, a first push, a force-push) — the gates would see an empty diff and pass vacuously. `taller ci` must fail with `result: error` instead. *Pinned in Task 2.*
4. **The snapshot missing, or carried on the branch** — a project adopted before it existed, or a branch that committed its own. CI must refuse rather than resolve (§4.6). *Pinned in Task 2.*
5. **`taller stage` with no Docker, or a profile that defines no staging** (`python-packaged`) — a clear refusal, and the live database untouched. *Pinned in Task 6.*

---

## File Structure

```
src/taller/commands/ci.py       `taller ci [--base REF] [--mode]`: the CI entry point
src/taller/commands/github.py   `taller github protect|status`: prints, never changes
src/taller/commands/stage.py    `taller stage <id>`: the staging run
src/taller/prs.py               pull request title/body from a ticket and its verdicts; create via gh
src/taller/catalogue/scaffolds/*/.github/workflows/taller-ci.yml   three scaffolds
src/taller/scaffold.py          the workflow ships with a new project
src/taller/adopt.py             the workflow is written at adoption; the old review workflows retire
src/taller/chief.py             ⑧ opens the pull request; ⑨ names `taller stage`
src/taller/doctor.py            the F rows: CI green on main; branch protection on
tests/unit/test_ci.py  test_prs.py  test_github.py  test_stage.py  test_publishing.py
tests/acceptance/test_github_flow.py
tests/stub_docker.py            a fake `docker`, as `stub_claude.py` is a fake `claude`
```

---

### Task 1: Safe to publish

**Files:** Modify `tests/acceptance/test_empty_hub.py`, `tests/domain_vocabulary.txt`, `src/taller/paths.py`, `docs/superpowers/specs/2026-09-26-taller-design.md:5`, `docs/superpowers/plans/2026-09-28-phase-b-chief.md:13`. Create `tests/unit/test_publishing.py`.

**Interfaces — produces:** `paths.domain_vocabulary() -> Path` (the hub's `domain_vocabulary.txt`); the ignorance test reads the repository's list **plus** the hub's when it exists.

The repository's `tests/domain_vocabulary.txt` becomes a short generic example (`acme`, `northwind`, `example-corp`, and a comment saying the owner's real list belongs in her hub). Her words move to `~/.taller/domain_vocabulary.txt`, and `hub.GITIGNORE` gains that filename so the hub never commits it. `docs/` stops being exempt from the scan, because her name is leaving the spec; `tests/fixtures/` stays exempt, and the two list files stay exempt.

- [ ] **Step 1: Failing tests** — `test_the_repository_names_no_owner` (every tracked file, `docs/` included, against the repository list **and** the hub's when present, with the same word-boundary rule the existing test uses); `test_the_owners_own_list_lives_in_her_hub` (`paths.domain_vocabulary()` is under `paths.hub()`, and the hub's `.gitignore` covers it); `test_a_word_from_the_hub_list_is_scanned_too` (a made-up word written only into the hub's list appears in the words the scan uses — the word itself stays out of every non-exempt file, or the scan would flag this plan); `test_the_shipped_list_is_generic` (the repository's list holds none of the owner's own words: her name, her accounts, her business).
- [ ] **Step 2:** Run → fail. **Step 3:** Move the list, add `paths.domain_vocabulary()`, rewrite the scan, remove the owner line from the spec and the account-qualified pull request reference from the phase B plan. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `chore: nothing in this repository names its owner`

### Task 2: `taller ci`

**Files:** Create `src/taller/commands/ci.py`, `tests/unit/test_ci.py`. Modify `src/taller/cli.py`.

**Interfaces — produces:**

```python
def run(args, prompter) -> int          # 0 pass · 1 findings · 2 could not run
def classify(diff) -> str               # "ticket-files" | "full"
def annotations(findings) -> list[str]  # ::error file=...,line=...::message  (LOW/NIT → ::notice)
```

`taller ci [--base REF] [--head REF] [--path PROJECT] [--mode]`.
- `--mode` prints `full` or `ticket-files` and exits 0 — that is the whole informational job.
- Otherwise: `constitution.load_snapshot(project)`; `gate_diff.build(project, base, head)`; run `constitution`, `size` and `tests` (in CI the checkout *is* the project, so `tests_gate.run(project, ruleset)` — no separate `project=`); print each finding as a GitHub annotation plus a plain summary line per gate; exit 1 when any finding is BLOCKER/HIGH/MEDIUM, 0 when only LOW/NIT.
- `--base` defaults to `origin/main`, `--head` to `HEAD`. A base the checkout cannot resolve, or a missing snapshot, or a snapshot in the diff → print the reason and exit **2** (Review Focus 3 and 4): CI must not pass vacuously.
- Ticket-files-only → print one line and exit 0 without running a gate.

- [ ] **Step 1: Failing tests** — `test_a_clean_change_passes`; `test_a_hardcoded_colour_fails_with_an_annotation` (exit 1; output holds `::error file=static/css/app.css,line=2::` and the rule id); `test_only_low_findings_still_pass`; `test_a_ticket_file_only_push_exits_at_once` (no gate runs: a marker file the tests gate would have written is absent); `test_mode_prints_full_or_ticket_files`; `test_a_base_the_checkout_cannot_see_is_an_error_not_a_pass` (`--base` a sha that is not there → exit 2, "could not"); `test_a_missing_snapshot_is_an_error` (exit 2, names `taller resolve`); `test_a_branch_carrying_the_snapshot_is_an_error` (exit 2); `test_ci_resolves_nothing` (no hub in `HOME`: still exit 0/1, never a crash).
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(ci): the three model-free gates, against the committed snapshot`

### Task 3: The workflow, shipped and adopted

**Files:** Create `src/taller/catalogue/scaffolds/{flask-sqlite,static-site,python-packaged}/.github/workflows/taller-ci.yml`, `tests/unit/test_workflow.py`. Modify `src/taller/scaffold.py` (the file ships with a new project), `src/taller/adopt.py` (written at adoption; the superseded workflows retire), `src/taller/commands/project.py` (the brief lists them), `tests/unit/test_adopt.py`.

The workflow, identical in all three scaffolds:
- `on: [push, pull_request]`, no `paths-ignore` anywhere.
- Job `gates`, `name: taller-ci`: checkout with `fetch-depth: 0`, set up Python 3.11, `pip install "$TALLER_SOURCE"` — from the hub setting `ci.taller_source`, substituted when the file is written, so the shipped scaffold names no one's account — then the project's own `requirements*.txt` when present, then `taller ci --base "$BASE"` where BASE is the pull request's base sha or `github.event.before` for a push.
- Job `mode`, `name: taller-ci-mode`: the same checkout, then `taller ci --mode`.
- A comment saying how to pin Taller to a tag instead of `main`.

Adoption: `.github/workflows/{code-review,security,design-review}.yml` join `adopt.REVIEW_DIRS` in the brief as *"replaced by Taller's checks — removed in the adoption commit"*, with the same keep-them choice; `taller-ci.yml` is written in the adoption commit either way.

- [ ] **Step 1: Failing tests** — `test_every_scaffold_ships_the_workflow`; `test_the_workflow_has_both_check_names_and_no_paths_ignore` (parse the YAML: job `gates` name `taller-ci`, job `mode` name `taller-ci-mode`, no `paths-ignore` key anywhere, `fetch-depth: 0`); `test_the_workflow_installs_taller_without_a_secret` (no `secrets.` reference); `test_the_shipped_workflow_names_no_account` (the scaffold file holds `%%taller_source%%`, not a URL); `test_the_written_workflow_carries_the_configured_source`; `test_a_new_project_has_the_workflow`; `test_adoption_writes_the_workflow_and_retires_the_old_ones` (a repository with `code-review.yml` → gone from the adoption commit, `taller-ci.yml` present); `test_the_owner_can_keep_the_old_workflows`; `test_adoption_writes_the_workflow_even_when_gh_is_absent` (Review Focus 2).
- [ ] **Step 2:** Run → fail. **Step 3:** Write the files and the two writers. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(ci): every project ships the workflow; adoption retires the old ones`

### Task 4: The pull request at ⑧

**Files:** Create `src/taller/prs.py`, `tests/unit/test_prs.py`. Modify `src/taller/chief.py` (stage `pr`), `src/taller/tickets.py` (`pr` in `STATUS_KEYS`), `tests/unit/test_chief.py`.

**Interfaces — produces:**

```python
def body(project: Path, ticket: Mapping) -> str        # ticket.md's words, the verdicts, MEDIUM findings, the plan
def title(ticket: Mapping) -> str                      # "<kind>: <title> (ticket NNNN)"
def create(project: Path, ticket: Mapping) -> tuple[int | None, str]   # (number, "") | (None, reason)
```

`create` uses `gh pr create --base main --head <branch> --title … --body-file -`, and returns `(None, "")` when the project has no GitHub remote — the same shape `issues.open_issue` already uses. The body references the issue as `Refs #N`, never `Closes #N`: Taller closes the issue itself at ⑫ (§13), and a closing keyword would have GitHub do it at merge instead.

The chief at ⑧: `prs.create`; on success store `pr` in `status.yml` and say the URL; on `(None, "")` say there is no GitHub remote and that she can merge locally (Review Focus 1); on `(None, reason)` say the reason and that the branch can still be merged by hand (Review Focus 2). Either way the stage still waits for the merge, as today.

- [ ] **Step 1: Failing tests** — `test_the_body_carries_the_owners_words_the_verdicts_and_the_plan`; `test_the_body_references_the_issue_without_closing_it` (`Refs #7`, and `Closes` appears nowhere); `test_medium_findings_are_in_the_body`; `test_the_pull_request_number_is_stored_on_the_ticket`; `test_a_project_without_a_remote_is_told_to_merge_locally` (stage stays `pr`, not blocked, and the note says so); `test_gh_signed_out_reports_the_reason_and_does_not_block`; `test_the_pull_request_is_created_once` (a second run at ⑧ with a stored `pr` does not call `gh pr create` again).
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(pr): a ticket reaching 8 becomes a pull request that carries its evidence`

### Task 5: What GitHub says, and what to turn on

**Files:** Create `src/taller/commands/github.py`, `tests/unit/test_github.py`. Modify `src/taller/cli.py`, `src/taller/doctor.py`.

**Interfaces — produces:**

```python
def protection(repo: str) -> dict          # {"ok": bool, "detail": str} from `gh api` rulesets
def latest_ci(repo: str) -> dict           # {"state": "green"|"failed"|"none"|"unknown", "detail": str}
def ruleset_instructions(repo: str) -> str # the exact thing for her to turn on
```

`taller github status [--path]` prints both; `taller github protect [--path]` prints `ruleset_instructions` — the GitHub screen to open and the equivalent `gh api` call, and states plainly that Taller will not change the setting itself. Doctor gains two F rows: *"`<name>`: latest taller-ci run on main is green"* (from `latest_ci`, which only counts a run whose `taller-ci-mode` says `full` — §15.4) and *"`<name>`: a pull request and a green taller-ci are required to merge"*. A project with no remote, or no `gh`: both rows **skip** with the reason, never fail.

- [ ] **Step 1: Failing tests** (a stub `gh` on PATH, as `stub_claude` does for `claude`) — `test_a_green_full_run_passes`; `test_a_green_ticket_files_run_does_not_count` (state `unknown`, doctor skips); `test_a_failed_run_is_reported`; `test_no_remote_and_no_gh_skip_with_a_reason`; `test_protection_missing_is_reported_with_what_to_turn_on`; `test_protect_prints_and_changes_nothing` (no `gh api --method POST|PUT|PATCH` in the stub's recorded argv).
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(github): what GitHub says, and the rule to turn on - never changed for her`

### Task 6: `taller stage`

**Files:** Create `src/taller/commands/stage.py`, `tests/stub_docker.py`, `tests/unit/test_stage.py`. Modify `src/taller/cli.py`, `src/taller/chief.py` (stage `staging`), the flask and static-site `docker-compose.staging.yml` (a `./data-staging/` bind mount in place of the named volume, matching §13.1), `src/taller/catalogue/profiles/*.yml` (a `staging:` block naming the compose files and the port).

**Interfaces — produces:**

```python
def command(project: Path, name: str, ruleset: Mapping) -> list[str]   # the docker compose argv
def prepare_data(project: Path, ruleset: Mapping) -> str               # what it copied, for the report
def run(args, prompter) -> int
```

`taller stage <ticket id> [--path]`: refuse unless the ticket is at ⑨ with a branch; `prepare_data` copies the production database named by `smoke.database` into `./data-staging/` (the file only, never `-wal`/`-shm`, and never opened); `command` is `docker compose -p <project>-staging -f docker-compose.yml -f docker-compose.staging.yml up -d --build`, run in the ticket's worktree; then GET the staging URL once and report it. No Docker → a refusal naming it. A profile with no `staging` block (`python-packaged`) → a refusal saying this project has no staging (Review Focus 5). The chief at ⑨ keeps waiting for her approval and names the command.

- [ ] **Step 1: Failing tests** — `test_the_compose_command_is_the_spec_s` (exact argv); `test_the_data_is_a_copy_and_the_live_file_is_untouched` (the source database's bytes and modification time unchanged; no `-wal`/`-shm` copied); `test_it_runs_in_the_tickets_worktree`; `test_no_docker_is_a_clear_refusal`; `test_a_profile_without_staging_refuses`; `test_a_ticket_not_at_staging_refuses`; `test_the_staging_url_is_reported`; `test_the_chief_names_the_command_at_staging`.
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** Run → pass; suite green.
- [ ] **Step 5: Commit** `feat(stage): a full ticket can be seen running before it is released`

### Task 7: The proof — criteria 16, 17, 18

**Files:** Create `tests/acceptance/test_github_flow.py`.

On an empty HOME, with a stub `gh` and a stub `docker`: `project new` (flask) → the workflow is there (criterion 16) and `taller ci` passes on the fresh project; a ticket whose implementer hardcodes a colour → `taller ci` exits 1 naming `brand.hardcoded-color`, and exits 0 once fixed; a ticket carried to ⑧ → a pull request whose body holds the verdicts, with the ticket's `pr` stored; `taller stage` brings up staging against a copy (criterion 17); `taller doctor` green with the F rows passing and nothing skipped for this project (criterion 18); the same run asserts no `ANTHROPIC_API_KEY` and no hub were needed by `taller ci`.

- [ ] Write · run · suite green · commit `test(acceptance): a project checked on GitHub, staged, and green in doctor`

---

## Deferred, recorded rather than forgotten

| Item | Why not now |
|---|---|
| A self-hosted runner so staging deploys itself (§13.1) | The spec defers it: infrastructure to maintain in exchange for not typing one command |
| Pinning CI to a released Taller version rather than `@main` | Needs a release process; the workflow carries the comment saying how |
| The cockpit's GitHub column | Phase E |
| Her own `taller` repository getting the workflow | It is not one of her registered projects; its suite is this plan's proof |
