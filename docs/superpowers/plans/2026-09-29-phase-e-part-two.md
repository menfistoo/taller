# Cockpit part two — Spend, Constitution, Settings, Health, and the interview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish spec §12 — the four remaining cockpit screens, the twelve onboarding questions as a web form, and the two things part one's reviewer found missing from the Ticket screen (`change`, and pull request state read from `gh`).

**Architecture:** One reading module per screen beside part one's `reading.py`, each a pure read over the same library the CLI uses; `views.py` routes and nothing more; every write is the library call the terminal makes, under the locks of §10.3. No database, no cache, no background work except the ticket runs part one already starts.

**Tech Stack:** Flask 3, Jinja2, Bootstrap 5 from its CDN, PyYAML — all already dependencies.

**Spec:** `docs/superpowers/specs/2026-09-26-taller-design.md`

## Global Constraints

- Bound to `127.0.0.1`, no authentication, one operator (§1.1). Every form carries `cockpit.TOKEN_FIELD` and every write calls `cockpit.check_token()`; the `Host` check in `cockpit/__init__.py` already covers every route.
- **No database** (§12). Every figure is read from `~/.taller/projects.json`, each project's `.taller/work/*/status.yml`, the verdict files, the hub's own files, and git.
- The cockpit **writes the same files the CLI writes, under the locks in §10.3** — always through an existing library call, never by writing YAML or running git itself.
- The cockpit never hosts the chief (§3.1) and never dispatches a model. No route in this plan calls `inference`, `chief` or `claude`.
- `spend.cost` is shown **only when `billing.mode == api`** (§5.2, §7.5); `pricing` and `cost` are hidden entirely otherwise.
- `spend.partial: true` renders as a lower bound (§7.5).
- Taller's own UI is English; code, comments and identifiers are English.
- A page must not grow without bound: every list this plan adds is capped, as part one's are.
- Tests never run the real `claude`: `tests/stub_claude.py` stands in, via the `stub_claude` fixture.

## Review Focus

1. **A rule edited while the project is on a ticket branch.** `taller amend` refuses off `main` (`commands/amend.py:35`); the browser must say so and write nothing, not commit a rule onto a ticket branch. — Task 4.
2. **A file path posted to the Constitution screen that is not one of the resolved sources.** A form field naming `../../.ssh/config` must be refused by name, not written. — Task 4.
3. **A settings value that is not valid YAML, or a key nothing declares.** Her words back, nothing written, the page still usable. — Task 2.
4. **Spend on a subscription.** No currency anywhere — not in a ticket row, not in a week, not in a total — whatever `pricing` holds. — Task 1.
5. **The interview answered in two tabs, or resumed from a half-finished answers file.** The answers file is shared state keyed by project name; the second tab must not silently overwrite the first's answers or create the project twice. — Task 6.

---

## File structure

| File | Responsible for |
|---|---|
| `cockpit/spending.py` | Spend: what each ticket, week and model has cost, and which tickets are past a threshold |
| `cockpit/configuration.py` | Settings: every effective key with the layer it came from, and one write |
| `cockpit/health.py` | Health: which projects can be checked, and one check when asked |
| `cockpit/rules.py` | Constitution: the resolved slices with their source files, and one amendment |
| `cockpit/interview.py` | The twelve questions as a form: one question at a time, through the same library |
| `cockpit/views.py` | Routes only (modified) |
| `cockpit/templates/*.html` | One template per screen, plus the nav (modified `base.html`) |
| `src/taller/tickets.py` | `reword` (modified) |
| `src/taller/prs.py` | `state` (modified) |

---

### Task 1: Spend

**Files:**
- Create: `cockpit/spending.py`, `cockpit/templates/spend.html`
- Modify: `cockpit/views.py`, `cockpit/templates/base.html` (the nav: Board, Spend, Health, Rules, Settings)
- Test: `tests/unit/test_cockpit_spend.py`

**Interfaces — produces:**

```python
WEEKS_SHOWN = 12
TICKETS_SHOWN = 50

def figures() -> dict        # {"mode", "show_cost", "totals", "tickets", "weeks", "models",
                             #  "warn_at", "stop_at", "partial"}
                             # NOT `spend()`: this module imports `taller.spend`, and a
                             # function of the same name would shadow it.
```

Each ticket row: `{"project", "id", "title", "url", "label", "weighted", "total", "cost",
"partial", "budget"}` where `budget` is `spend.budget(ticket, cfg)`'s `ok`/`warn`/`stop`.
A week row: `{"week", "weighted", "cost", "tickets"}`, `week` being the ISO week of the
ticket's `created` date (`date.fromisoformat(ticket["created"][:10]).isocalendar()`),
newest first — `status.yml` keeps no per-dispatch timestamps, so the week a ticket belongs
to is the week it was opened, and the template says so in one line.
A model row: `{"model", "input", "cache_write", "cache_read", "output", "weighted"}`,
summed across every ticket of every project, largest `weighted` first.

`show_cost` is `billing.mode(cfg) == "api"`; when it is false no row carries a `cost` and
the template renders no currency at all. `mode` comes from `billing.mode(config.load_hub_config())`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_cockpit_spend.py`

```python
def test_each_ticket_shows_its_weighted_tokens_and_where_it_stands(project, client):
    # two tickets: one under per_ticket_warn, one over it
    assert [row["budget"] for row in found["tickets"]] == ["ok", "warn"]
    assert "400,000" in page or "400000" in page        # her configured warning line

def test_on_a_subscription_there_is_no_currency_anywhere(project, client):
    # cfg billing.mode subscription, a pricing table present, spend recorded
    assert found["show_cost"] is False
    assert all(row["cost"] is None for row in found["tickets"])
    assert "$" not in page and "USD" not in page.upper()

def test_on_api_billing_the_cost_is_shown(project, client, monkeypatch):
    # ANTHROPIC_API_KEY set, pricing present
    assert found["show_cost"] is True and found["totals"]["cost"] > 0

def test_a_lower_bound_is_marked(project, client):
    # spend.partial true on one ticket
    assert "at least" in page.lower()

def test_weeks_are_by_the_week_the_ticket_was_opened(project, client):
    # two tickets created in different ISO weeks
    assert [w["week"] for w in found["weeks"]] == ["2026-W40", "2026-W39"]

def test_a_project_that_cannot_be_read_does_not_empty_the_page(project, client):
    # one project's folder moved; the other's tickets still counted
```

- [ ] **Step 2: Run them** — `python -m pytest -q -p no:cacheprovider tests/unit/test_cockpit_spend.py`. Expected: FAIL, `No module named 'cockpit.spending'`.
- [ ] **Step 3: Implement `figures()` in `cockpit/spending.py`** — reads `reading.projects()` for the paths, `tickets.list_tickets` for each ticket's `spend` block, `spend.weighted`/`spend.budget` and `billing.mode`/`billing.cost` for the figures. Closed tickets count: spend does not stop mattering when a ticket closes.
- [ ] **Step 4: Add `GET /spend`** in `views.py` rendering `spend.html`, and the nav in `base.html`.
- [ ] **Step 5: Run them** — Expected: PASS.
- [ ] **Step 6: Commit** `feat(cockpit): spend, by ticket, week and model`

---

### Task 2: Settings

**Files:**
- Create: `cockpit/configuration.py`, `cockpit/templates/settings.html`
- Modify: `cockpit/views.py`
- Test: `tests/unit/test_cockpit_settings.py`

**Interfaces — consumes:** Task 1's nav. **Produces:**

```python
def rows(project_name: str | None = None) -> dict   # {"rows", "project", "projects", "mode"}
def save(key: str, raw: str, project_name: str | None) -> list[tuple[str, str]]
```

`rows` calls `settings.effective(project)`; each row is `{"key", "value", "source", "editable"}`
with `value` rendered by `yaml.safe_dump(value, default_flow_style=True).strip()` so what she
sees is what she may type back. When `billing.mode` is not `api`, every key whose first segment
is `pricing` and every key ending `.cost` is dropped entirely (§12). `save` is
`settings.set_value(key, raw, project)` — nothing else; its return is what was refreshed, and
the page shows those lines.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_key_shows_the_layer_it_came_from(project, client):
    assert ("thresholds.max_file_lines", 800, "default") in [(r["key"], r["value"], r["source"]) for r in found["rows"]]

def test_pricing_and_cost_are_hidden_off_api_billing(project, client):
    assert not [r for r in found["rows"] if r["key"].startswith("pricing")]

def test_changing_a_value_writes_it_through_the_library(project, client):
    # POST key=thresholds.max_file_lines value=500
    assert settings.effective(project)  # the new value, source "project"
    assert "refreshed" in page.lower()

def test_a_value_that_is_not_yaml_is_refused_with_her_words(project, client):
    # POST value="{oops"
    assert answer.status_code == 200 and "refused" not in page  # a sentence, not a trace
    assert settings.effective(project)  # unchanged

def test_a_key_nothing_declares_is_refused(project, client):
    # POST key=made.up.key
    assert "made.up.key" in page

def test_a_settings_write_needs_the_token(project, client):
    assert client.post("/settings", data={"key": "x", "value": "1"}).status_code == 400
```

- [ ] **Step 2: Run them.** Expected: FAIL, `No module named 'cockpit.configuration'`.
- [ ] **Step 3: Implement `rows` and `save`** in `cockpit/configuration.py`, and `GET /settings`, `POST /settings` in `views.py` — the POST reuses part one's `views._write` shape: check the token, call the library, flash what came back or the refusal, redirect.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cockpit): settings, every key and the layer it came from`

---

### Task 3: Health

**Files:**
- Create: `cockpit/health.py`, `cockpit/templates/health.html`
- Modify: `cockpit/views.py`
- Test: `tests/unit/test_cockpit_health.py`

**Interfaces — produces:**

```python
def projects() -> list[dict]        # {"name", "path", "available", "problem", "checked"}
def check(project_name: str) -> dict  # scan.health's figures, plus {"name", "seconds", "when"}
def last_dir() -> Path       # paths.run_dir() / "cockpit-health"; one <name>.json per
                             # project, the last check. A function, not a constant: the
                             # home directory is read when it is asked for.
```

Her decision: **no page load runs a scan.** `GET /health` lists the projects with whatever
last check is on disk (`last_dir()/<name>.json`, written by `check`); `POST /health/<name>` runs
`scan.health(path, constitution.resolve(path))`, stores it, and redirects back. The stored
figures carry `when` (ISO seconds) so the page can say how old they are.

- [ ] **Step 1: Write the failing tests**

```python
def test_opening_the_page_scans_nothing(project, client, monkeypatch):
    monkeypatch.setattr(scan, "health", lambda *a, **k: pytest.fail("the page scanned"))
    assert client.get("/health").status_code == 200

def test_checking_one_project_reports_its_findings_and_its_tests(project, client):
    # POST /health/toolshed
    assert found["counts"]["medium"] >= 1 and "tests_run" in found["tests"]

def test_the_figures_are_kept_and_shown_with_their_age(project, client):
    assert "checked" in page.lower() and found["when"]

def test_a_project_whose_snapshot_is_missing_says_so(project, client):
    # .taller/resolved.json removed -> constitution.resolve still works; a project
    # that is not registered is refused by name
    assert "not registered" in page or "cannot be read" in page

def test_checking_needs_the_token(project, client):
    assert client.post("/health/toolshed", data={}).status_code == 400
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `cockpit/health.py` and the two routes.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cockpit): health, checked when you ask for it`

---

### Task 4: The constitution, read and amended

**Files:**
- Create: `cockpit/rules.py`, `cockpit/templates/rules.html`
- Modify: `cockpit/views.py`
- Test: `tests/unit/test_cockpit_rules.py`

**Interfaces — produces:**

```python
def slices(project_name: str) -> dict
    # {"project", "projects", "slices": [{"name", "sources": [{"path", "where", "text",
    #   "editable"}]}], "overrides": [...], "hub_sha", "snapshot_sha", "branch"}
def save(project_name: str, path: str, text: str, reason: str) -> list[str]
```

`slices` is built from `constitution.resolve(path)["slices"]`: each source is one file on
disk, read on its own — **never the concatenation**, because an edit has to go back to the
file it came from. `where` is `"hub"` when the path is under `paths.hub()`, else `"project"`.

`save` is the amendment (§4.5, `commands/amend.py`):
1. `path` must be one of the resolved sources for this project, compared **resolved**
   (`Path(path).resolve()` against each source's `.resolve()`); anything else raises
   `ConfigError` naming the path. This is the only check standing between a form field and
   any file on the machine.
2. `reason` is required — `ConfigError` when empty, exactly as `taller amend` requires it.
3. A **project** file: refuse unless the project is on `main` (`gitio.git(project,
   "rev-parse", "--abbrev-ref", "HEAD")`), then write, `gitio.git add/commit -m f"amend: {reason}"`,
   then `generated.refresh(project)`.
4. A **hub** file: write, `hub.commit(f"amend: {reason}")` under the hub lock, then
   `generated.refresh_affected(module=<module id>)` — or `everything=True` when the file is a
   profile or `taller.yml`, as `amend._refresh_hub` decides.
5. Returns the lines to show her: what was amended and what was refreshed.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_slice_shows_its_files_and_where_they_come_from(project, client):
    assert [s["name"] for s in found["slices"]]        # product, stack, conventions, ...
    assert any(src["where"] == "hub" for s in found["slices"] for src in s["sources"])

def test_saving_a_project_rule_commits_it_and_refreshes_the_snapshot(project, client):
    # POST path=<project>/.taller/constitution/conventions.md text=... reason="Tabs are out"
    assert "amend: Tabs are out" in git_log(project)
    assert "Tabs are out" in (project / ".taller" / "resolved.json").read_text()

def test_saving_a_hub_rule_refreshes_every_project_that_uses_it(project, client):
    assert "refreshed toolshed" in " ".join(lines)

def test_a_rule_cannot_be_amended_while_the_project_is_on_a_ticket_branch(project, client):
    # git checkout -b ticket/0001-x
    assert "main" in page and git_status(project) == ""      # nothing written

def test_a_path_that_is_not_one_of_the_files_is_refused(project, client):
    # POST path="../../../.ssh/config"
    assert answer.status_code == 200 and "is not one of" in page
    assert not (tmp_home / ".ssh" / "config").exists()

def test_an_amendment_with_no_reason_is_refused(project, client):
    assert "reason" in page.lower() and git_head(project) == before
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `cockpit/rules.py`, `GET /rules`, `POST /rules/<project>`.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cockpit): the constitution, read and amended in the browser`

---

### Task 5: The Ticket screen's third action, and the pull request as GitHub sees it

**Files:**
- Modify: `src/taller/tickets.py`, `src/taller/prs.py`, `cockpit/reading.py`, `cockpit/views.py`, `cockpit/templates/ticket.html`
- Test: `tests/unit/test_ticket_reword.py`, `tests/unit/test_cockpit_ticket.py` (add)

**Interfaces — produces:**

```python
# src/taller/tickets.py
def reword(project: Path | str, ticket_id: int, *, title: str, words: str) -> Ticket

# src/taller/prs.py
def state(project: Path | str, ticket: Mapping[str, Any]) -> dict
    # {"number": int|None, "state": str, "url": str, "checks": str, "problem": str}
```

`reword` is spec §12's **change**: her ask, changed, while changing it still means anything.
Under the project lock, written to `main` with a note, and **refused once the ticket has left
③ design** (`tickets.stage_number(ticket["stage"]) > 3`) with a sentence pointing at reject —
after ④ there is a branch and a plan built on the old words, and §7.2 already has a way to
send those back. An empty title or empty words is refused.

`state` asks `gh` (`discovery._run_gh(["pr", "view", str(number), "--repo", repo, "--json",
"state,url,mergeable,statusCheckRollup"])`) for the number on the ticket; `{"number": None}`
when the ticket has none, and `problem` (never an exception) when `gh` is missing, not
authenticated, or the repository is unknown. The Ticket page shows it beside the recorded
number, so a pull request merged or closed on GitHub stops reading as open here.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_ticket_reword.py
def test_the_ask_can_be_changed_before_the_work_starts(project):
    ticket = tickets.reword(project, 1, title="Heading colour", words="Use the brand red.")
    assert tickets._words(project, ticket).strip() == "Use the brand red."
    assert "reworded" in notes_of(project, ticket)

def test_changing_the_ask_after_design_is_refused(project):
    # stage build
    with pytest.raises(ConfigError) as refused: tickets.reword(...)
    assert "reject" in str(refused.value)

def test_an_empty_ask_is_refused(project):

# tests/unit/test_cockpit_ticket.py
def test_the_change_form_is_only_offered_while_it_would_mean_something(project, client):
def test_changing_the_ask_from_the_browser_writes_it(project, client):
def test_the_pull_request_is_shown_as_github_has_it(project, client, monkeypatch):
    # _run_gh stubbed to return state MERGED
    assert "merged" in page.lower()
def test_github_being_unreachable_is_one_line_not_a_broken_page(project, client, monkeypatch):
    # _run_gh returns None
    assert answer.status_code == 200 and "gh" in page
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `tickets.reword`, `prs.state`, the `change` form on `ticket.html`, `POST /ticket/<project>/<id>/change`, and `page["pr_state"]` in `reading.ticket_page`.
- [ ] **Step 4: Run them.** Expected: PASS. Then `python -m pytest -q -p no:cacheprovider tests/unit/test_cockpit_ticket.py tests/unit/test_cockpit_writes.py` — Expected: PASS, part one still green.
- [ ] **Step 5: Commit** `feat(cockpit): change what you asked for, and see the pull request as GitHub has it`

---

### Task 6: The twelve questions as a web form

**Files:**
- Create: `cockpit/interview.py`, `cockpit/templates/interview.html`, `cockpit/templates/brief.html`
- Modify: `cockpit/views.py`, `cockpit/templates/board.html` (a "New project" button)
- Test: `tests/unit/test_cockpit_interview.py`

**Interfaces — produces:**

```python
def start(name: str, path: str) -> dict           # refuses a bad name or a non-empty folder
def page(name: str) -> dict                       # {"name", "question", "number", "choices",
                                                  #  "answered", "total", "brief", "answers"}
def answer(name: str, key: str, raw: str | list[str]) -> dict   # {"ok", "problem"}
def create(name: str, path: str) -> dict          # {"project", "report"}
```

**The identical question list, through the identical library code** (§12): the page renders
`onboarding.QUESTIONS[n]` with `onboarding.profile_choices()` / `onboarding.brand_choices()`,
and `answer` validates by calling `onboarding.ask_one(AnswerSheetPrompter({key: raw}), question,
answers)` — the same validation the terminal uses. `prompter.NeedsAnswer` means the answer was
not acceptable and becomes `{"ok": False, "problem": ...}`. An accepted answer is stored with
`onboarding.save_progress(name, answers)`, so an interview started in a terminal continues in
the browser and the other way round.

`create` calls `scaffold.create_project(target, name=name, profile=answers["profile"],
brand=answers["brand"], answers=answers)` then `onboarding.discard_progress(name)` — the same
two calls `commands/project.py:67-69` makes. It refuses when any of the twelve is unanswered,
and when the folder now exists and is not empty.

Two things the browser cannot do, each refused with a sentence rather than half-done:
- **The hub is not set up yet** (`setup_command.needed()`): `start` refuses and says to run
  `taller setup` in a terminal first — that interview is §4.7's, not §11's.
- **Making a new brand**: the brand question offers the brands that exist and `none`;
  `__new__` is not offered, and the page says `taller brand new` makes one.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_questions_are_the_same_twelve_in_the_same_order(client):
    assert [q.id for q in onboarding.QUESTIONS] == [...]   # the page shows q1 first
def test_an_answer_is_validated_by_the_same_code_the_terminal_uses(tmp_home):
    assert interview.answer("toolshed", "users", "not one of them")["ok"] is False
def test_the_answers_file_is_the_one_the_terminal_reads(tmp_home):
    assert onboarding.load_progress("toolshed")["what_it_does"] == "Keeps track of tools."
def test_an_interview_started_in_a_terminal_carries_on_in_the_browser(tmp_home):
    onboarding.save_progress("toolshed", {"what_it_does": "..."} )
    assert interview.page("toolshed")["answered"] == 1
def test_the_brief_is_shown_before_anything_is_created(client, tmp_home):
    assert "toolshed" in page and not (projects / "toolshed").exists()
def test_creating_it_makes_the_project_and_forgets_the_answers(client, tmp_home):
    assert (projects / "toolshed" / ".taller").is_dir()
    assert onboarding.load_progress("toolshed") == {}
def test_a_second_tab_cannot_create_it_twice(client, tmp_home):
    # create, then POST create again with the same name
    assert "exists" in page.lower() and registry.list_projects() == one
def test_a_hub_that_is_not_set_up_says_so_instead_of_asking_twelve_questions(tmp_home):
    assert "taller setup" in interview.start("toolshed", str(projects))["problem"]
def test_making_a_brand_is_not_offered_here(client, tmp_home):
    assert onboarding.NEW_BRAND not in [value for value, _ in found["choices"]]
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `cockpit/interview.py` and the routes `GET /new`, `POST /new`,
      `GET /new/<name>`, `POST /new/<name>`, `POST /new/<name>/create`.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cockpit): the twelve questions, as a form`

---

### Task 7: The proof — a project made and run from the browser

**Files:** Create `tests/acceptance/test_cockpit_part_two.py`

On an empty HOME with the stub `claude`, through the test client only: `taller setup`'s hub is
prepared by the existing helper, then the interview answers all twelve and creates a real
project; Settings shows `thresholds.max_file_lines` from `default` and changing it moves the
source to `project`; the Constitution screen amends one project rule, and `.taller/resolved.json`
carries the new text; Health checks the project and reports its tests figures; a ticket is run
to ⑦ by the chief, and Spend shows its weighted tokens with no currency on the page; finally
`taller doctor` is still green and `git status` in the project is clean.

- [ ] Write · run · whole suite green · commit `test(acceptance): a project made, settled and measured from the browser`

---

## Deferred, recorded rather than forgotten

| Item | Why not now |
|---|---|
| Live spend per dispatch, with timestamps | `status.yml` stores a rollup, not a log (§7.5); a week is the week the ticket was opened until the store changes |
| Making a brand in the browser | `taller brand new` opens a page and asks for tokens; it is its own screen |
| `taller setup` as a web form | §4.7's interview is about this machine, and it is what makes the cockpit runnable at all |
| Editing `overrides.md` with a form per override | It is a rule file like the others; the text box amends it the same way |
