# Phase G, second half — what it uses, and her connected services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Taller becomes usable by its owner, who is not an engineer: her projects and what she asked for, in her own words; what each project is, its rules and its look, which she can read and change; the work starting by itself; and nothing ever leaving her machine until she presses a button.

**This is the second half of Phase G.** It assumes the first half (`2026-09-29-phase-g1-plain-front.md`) is merged: the plain front, `cockpit/words.py`, `cockpit/plain.py`, the stylesheet and the settings pages exist. References to *first-half Task N* point into that plan.

**The look was agreed from two mock-ups before this plan was executed:** `.superpowers/mockups/phase-g-usage.html` and `.superpowers/mockups/phase-g-services.html`. They are git-ignored on purpose: they carry her project's name and example content, and this repository is public. Where the words in a task and a mock-up differ, the mock-up wins.

**Architecture:** A second, plain front at `/`, built from the same reading library as the existing screens — which keep working, at `/board`, for the day something goes wrong. One new module turns the machine's state into her words, one file holds every word shown, and one stylesheet carries the look; no framework, no CDN, no build step. Publishing becomes a decision instead of a side effect: `gitio` stops pushing unless a setting says otherwise, a fourth sync state records work held back, and one command and one button send it.

**Tech Stack:** Flask 3, Jinja2, one hand-written stylesheet served from `cockpit/static/`. Bootstrap stays on `/board` only.

**Spec:** `docs/superpowers/specs/2026-09-26-taller-design.md`

**Why this plan exists (2026-09-29):** the owner is not an engineer, and found the cockpit of phase E unreadable: stage numerals, lanes, gate names and rule ids. What she asked for instead: her projects; the work going on by itself; asking for things; seeing progress and the result; and **nothing published until she says so**. She asked, twice, for great care on the look: a program for its owner, not for an engineer. On the first mock-up she asked for the project's rules, its key facts and its brand to be reachable too; later, to see which models and plugins the work uses and what it consumes, and to list, search and add connected services.

**Measured on her machine before this plan was executed (2026-09-29).** Four one-word requests to `haiku`, run the way Taller runs a dispatch: everything loaded, **29,750** tokens of context; without MCP servers (`--strict-mcp-config`), 26,771; also without user settings and plugins (`--setting-sources project,local`), **24,961**; `--safe-mode`, 21,993. Her setup is about a quarter of every request's starting weight. Ticket 0001 on Taller itself, from asked to a plan: **544,374** weighted — `claude-haiku-4-5` 318,247 (the explorer, ~2.0 M cache reads, about 70 turns), `claude-opus-5-5` 178,146 (the architect), `claude-sonnet-5-5` 47,982 (the chief). Opus 5.5 and Sonnet 5.5 are used through the `opus` and `sonnet` aliases; Fable 5.1 is defined as `creative` and assigned to no role.

**Her connected services, read with `claude mcp list` the same day:** 24 entries — six through her Claude account (five connected, one needing sign-in), and eighteen brought by plugins, of which three were connected, eight had never been signed in, one was failing, and six were unconfigured duplicates of services already listed. She asked for the list to be seen, searched and added to — and, asked which she meant, for both: managing the list, and Taller's work using the services to create things for her. The public MCP registry (`registry.modelcontextprotocol.io/v0/servers?search=`) answers, but unfiltered: *drive* returned a car-rental service and an infrastructure tool, not Google Drive.

## Global Constraints

- **Nothing on the plain front may name the machine.** No stage numerals (① … ⑫), no "lane", "gate", "verdict", "checkpoint", "branch", "commit", "sha", "sync", "worktree", "blocker", "HIGH", "MEDIUM", no rule ids (`brand.hardcoded-color`). A test asserts this against every plain page, by word list.
- **One action per screen, and it is obvious.** Every page has one thing she is most likely to want, as a button at least 44px tall.
- **Taller's pages carry no brand of their own, and never the owner's** (spec §12's existing rule): neutral paper and ink, plus two state colours.
- **No CDN and no build step on the plain front.** One stylesheet at `cockpit/static/plain.css`, served by Flask. The cockpit must work with no internet.
- Bound to `127.0.0.1`, no authentication, the token on every form, the `Host` check (§1.1, part one).
- Every write goes through the same library call and the same locks the CLI uses (§10.3); the cockpit never writes `status.yml`, git or the registry itself, and never hosts the chief (§3.1).
- Taller's own interface is English; code, comments and identifiers are English.
- Tests never run the real `claude`: `tests/stub_claude.py` stands in.
- **Never `--bare`** (spec 3.6.2): it skips the subscription's sign-in. Taller's jobs shed her setup with `--strict-mcp-config` and `--setting-sources`, never with `--bare`.
- The word **token** appears nowhere on the plain front. Usage is shown as *how much of your plan it used*, with bars against her own other work.
- **Taller holds no credentials of its own** (spec 5.2), and that includes her connected services: an account service is signed in on claude.ai and used through her Claude account, never through a token Taller keeps. Taller never completes a sign-in on her behalf.
- **Nothing Taller's work creates in a service reaches another person.** It may add to *her* Todoist and *her* calendar; it never sends an email, a message or an invitation. Sending is deliberately not offered.
- **Every service is off for Taller's work until she turns it on**, per project, and each one is *May look* or *May look and add*, never more.

## Review Focus

1. **A service she allowed that has since signed out, or a notification that cannot be delivered** — the work carries on, the page says the service needs her, and nothing is retried in a loop against her account. — Tasks 6 and 8.
2. **A setup that breaks sign-in once her plugins and services are left out** — caught by `doctor`'s live check before the first ticket, not by the ticket. — Task 1.
3. **A ticket recorded before usage was kept by job** — *What it uses* says nothing for it rather than guessing. — Tasks 3 and 4.

---

## File structure

| File | Responsible for |
|---|---|
| `src/taller/publishing.py` | Whether publishing is automatic, what is waiting, and sending it |
| `src/taller/commands/publish.py` | `taller publish` |
| `src/taller/gitio.py` | Not pushing unless publishing is automatic; the `held` state (modified) |
| `src/taller/chief.py` | ⑧ waits for publishing instead of pushing (modified) |
| `cockpit/words.py` | **Every word the plain front shows**, and nothing else |
| `cockpit/plain.py` | The machine's state turned into those words. Pure; no Flask |
| `cockpit/static/plain.css` | The look: one stylesheet, no framework |
| `cockpit/templates/plain/*.html` | `base.html`, `home.html`, `thing.html`, `ask.html` |
| `cockpit/project_settings.py` | About it, its rules, its look, its choices: read in her words, written through the library |
| `src/taller/own_rules.py` | Her own *always* and *never* rules: kept apart from what the answers generate |
| `cockpit/templates/plain/settings/*.html` | `about.html`, `rules.html`, `look.html`, `choices.html` |
| `cockpit/usage.py` | What it uses: which model does which job, and where each thing's usage went |
| `cockpit/templates/plain/usage.html` | The "What it uses" page |
| `src/taller/spend.py` | `by_role` beside `by_model`, so usage can be told by job (modified) |
| `src/taller/inference.py` | Taller's jobs leave her connected services and plugins out (modified) |
| `src/taller/connections.py` | Her connected services: listed, grouped, and what each project may use |
| `src/taller/notify.py` | Telling her when something needs her, through a service she chose |
| `cockpit/templates/plain/services.html` | The "Connected services" page |
| `cockpit/views.py` | The new routes; the old board moves to `/board` (modified) |

---

### Task 1: Taller's jobs leave her connected services and plugins out

**Files:**
- Modify: `src/taller/config.py` (defaults), `src/taller/inference.py` (`_build`, lines 354-420), `src/taller/doctor.py` (its live dispatch check)
- Test: `tests/unit/test_dispatch_isolation.py`

**Interfaces — produces:** setting `dispatch.leave_out_my_setup`, default `True`.

When it is on, every dispatch's argv gains `--strict-mcp-config` (no `--mcp-config` given, so
**no** MCP server loads — her Gmail, Drive, Calendar and the rest are out of reach of every job)
and `--setting-sources project,local` (her user-level settings and plugins stay out; a project's
own `.claude/settings.json` still applies). `--safe-mode` is **not** used: it also drops a
project's `CLAUDE.md`, skills and hooks, and the CLI describes it as a troubleshooting mode.
`doctor`'s live dispatch check runs with the same flags, so a setup that breaks sign-in is caught
there first rather than by the first ticket.

- [ ] **Step 1: Write the failing tests**

```python
def test_by_default_a_job_loads_no_connected_services_and_no_plugins():
    argv, _ = inference._build(dispatch(role="explorer"), "claude")
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--setting-sources") + 1] == "project,local"

def test_it_can_be_turned_off(monkeypatch):
    # dispatch.leave_out_my_setup: false
    assert "--strict-mcp-config" not in argv and "--setting-sources" not in argv

def test_never_bare_and_never_safe_mode():
    assert "--bare" not in argv and "--safe-mode" not in argv

def test_doctor_checks_sign_in_the_way_jobs_run(stub_claude):
    assert "--strict-mcp-config" in stub_claude.calls()[-1]
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** the default, the flags and the doctor probe.
- [ ] **Step 4: Run them**, then `python -m pytest -q -p no:cacheprovider tests/unit -k "inference or doctor"`. Expected: PASS.
- [ ] **Step 5: Verify live, once, by hand** — `taller doctor` on her machine; its dispatch row must pass. This is the one step that uses her subscription; it is a single one-word request.
- [ ] **Step 6: Commit** `feat(inference): Taller's jobs leave your connected services and plugins out`

---

### Task 2: The price list knows the models that actually run

**Files:**
- Modify: `src/taller/config.py` (`pricing`), `src/taller/billing.py`, `src/taller/doctor.py`
- Test: `tests/unit/test_pricing_current.py`

`config.SHIPPED_DEFAULTS["pricing"]` gains `claude-opus-5-5` and `claude-sonnet-5-5`, with prices
**copied from Anthropic's published pricing page at execution time** and `as_of` set to that day —
never inferred from the older entries. `billing.cost` matches a dated id
(`claude-haiku-4-5-20251001`) to its undated entry. `doctor` gains one row: *a model that has run
is not in the price list*, a warning that only matters on `api` billing and says so.

- [ ] **Step 1: Write the failing tests** — `test_every_model_that_ran_on_ticket_0001_is_priced`,
      `test_a_dated_model_id_finds_its_price`, `test_doctor_names_an_unpriced_model_that_ran`.
- [ ] **Step 2: Run them.** Expected: FAIL — `claude-opus-5-5` is not in the table.
- [ ] **Step 3: Implement.** Record the page and the date the prices came from in the commit message.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `fix(billing): price the models that actually run`

---

### Task 3: Usage told by job

**Files:**
- Modify: `src/taller/spend.py` (`fold`), `src/taller/chief.py` / `src/taller/gates/llm.py` (pass the role to `fold`)
- Test: `tests/unit/test_spend_by_role.py`

**Interfaces — produces:** `status.yml`'s `spend` block gains `by_role: {role: {input,
cache_write, cache_read, output}}` beside `by_model`, filled by `spend.fold(..., role=...)`. A
ticket recorded before this has no `by_role`, and every reader treats it as absent, not as zero.

The shipped `budget` default already moved to *Normal* in the first half (its Task 12).

- [ ] **Step 1: Write the failing tests** — `test_each_job_is_counted_under_its_own_role`,
      `test_a_ticket_from_before_has_no_by_role_and_nothing_breaks`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them**, then `python -m pytest -q -p no:cacheprovider tests/unit -k "spend or budget or chief"`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(spend): usage by job`

---

### Task 4: What it uses

**Files:**
- Create: `cockpit/usage.py`, `cockpit/templates/plain/usage.html`
- Modify: `cockpit/words.py`, `cockpit/views.py`, `cockpit/templates/plain/base.html` (a link on every page)
- Test: `tests/unit/test_plain_usage.py`

**Interfaces — consumes:** Task 3's `by_role`; `config.resolve_model`; Task 1's setting.
**Produces:** `def usage() -> dict`, `def choose_strongest(for_job: str, on: bool) -> list[str]`.

One page, reached from a small *What it uses* link on every plain page. Three sections:

**Who does what** — one line per job, in words, with the model that actually ran most recently
for it (from `by_model`/`by_role`, not from the configuration, which only says what was asked for):

| Job (`words.JOBS`) | Roles |
|---|---|
| Understanding what you asked for | `chief` |
| Reading your project | `explorer` |
| Writing plans | `architect` |
| Making changes | `implementer`, `fixer` |
| Checking the work | `gate_security`, `gate_quality`, `gate_ux` |
| Writing summaries | `scribe`, `summariser` |

Models are named for people: *Claude Opus 5.5 — the most careful*, *Claude Sonnet 5.5*,
*Claude Haiku 4.5 — quick and light*, *Claude Fable 5.1 — the strongest, and the heaviest on your
plan*. Under it, one choice: **Use the strongest model for writing plans** and **for checking
security**, each a switch, off by default, writing `models.architect` / `models.gate_security` to
`creative` in the hub (and back to `thinker`).

**How much each thing used** — every thing she asked for, as a bar against her largest, newest
first, with *more than usual* marked when it is over twice her median. Beside each, where it
went, by job, as a short sentence: *Mostly reading your project*.

**What goes with every request** — one switch, *Leave my connected services and plugins out*
(Task 1's setting), and one sentence: *Your Gmail, Drive, Calendar and plugins are not needed for
this work. Leaving them out keeps them out of its reach and makes every request a little lighter.*

- [ ] **Step 1: Write the failing tests**

```python
def test_each_job_names_the_model_that_actually_ran(project_with_spend, client)
def test_fable_is_offered_for_plans_and_security_and_off_by_default(project, client)
def test_turning_on_the_strongest_for_plans_writes_the_hub(project, client)
def test_each_thing_says_where_its_usage_went(project_with_spend, client):
    assert "Mostly reading your project" in page
def test_a_thing_from_before_usage_by_job_says_nothing_rather_than_guessing(project, client)
def test_the_word_token_appears_nowhere(project_with_spend, client)
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `usage.py`, `usage.html`, `words.JOBS` and the two posts.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cockpit): what it uses, and where it went`

---

### Task 5: Her connected services, read — and the one question tested first

**Files:**
- Create: `src/taller/connections.py`
- Test: `tests/unit/test_connections.py`

**Step 0 is a measurement, run once on her machine, and it decides Task 6's mechanism.**
With the host session's variables removed (as `inference._environment` does), one-word `haiku`
requests, each recording its context size and whether the tool is present:

| Run | Flags |
|---|---|
| a | none |
| b | `--strict-mcp-config` |
| c | `--allowedTools "mcp__claude_ai_Google_Drive__*"` and `--disallowedTools` naming every other server's prefix |
| d | `--strict-mcp-config --mcp-config` with an entry for the Drive connector's URL only |

The actual tool prefix of an account service is read from run *a*'s `init` event
(`--output-format stream-json --verbose`), not assumed. The result goes in the ledger as a
ruling: **if (d) keeps Drive usable, Task 6 builds an `--mcp-config` per project; if only (c)
does, Task 6 blocks every other server by name** — which takes them out of reach, though their
definitions may still weigh on the request, and the page says so. If neither works, account
services stay all-or-nothing for Taller's work and Task 6's per-project choice covers plugin and
her own services only; that is ledgered and said to her plainly.

**Interfaces — produces:**

```python
def listed() -> list[dict]
    # {"name", "group": "account" | "plugin" | "yours", "state": "ok" | "sign_in" | "broken" | "unset",
    #  "made_by": str, "prefix": str, "duplicate_of": str | None}
def by_group() -> dict[str, list[dict]]
STATE_WORDS = {"ok": "Connected", "sign_in": "Needs you to sign in",
               "broken": "Not working", "unset": "Not set up"}
```

`listed()` runs `claude mcp list` once (60-second timeout, host session variables removed),
parses its lines, and groups them: `claude.ai …` → **account**, `plugin:<plugin>:<name>` →
**plugin** (with the plugin named), anything else → **yours**. An entry whose name repeats a
connected one and is `Not configured` is marked `duplicate_of`, so the page can fold the four
extra Gmails into one line. The result is cached for 60 seconds: listing health-checks every
server and takes several seconds.

- [ ] **Step 1: Write the failing tests** (on captured `claude mcp list` output, never live):
      `test_services_are_grouped_by_where_they_come_from`,
      `test_states_are_read_into_words`,
      `test_the_extra_gmails_fold_into_one`,
      `test_a_listing_that_fails_is_a_sentence_not_an_empty_page`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(connections): her connected services, read and grouped`

---

### Task 6: What each project's work may use

**Files:**
- Modify: `src/taller/connections.py`, `src/taller/inference.py` (`_build`), `src/taller/config.py`
- Test: `tests/unit/test_connections_allowed.py`

**Interfaces — produces:**

```python
LEVELS = ("off", "look", "look_and_add")
def allowed(project: Path | str) -> dict[str, str]         # service name -> level
def allow(project: Path | str, service: str, level: str) -> list[str]
```

Stored in the project's own `taller.yml` as `services: {"Google Drive": "look"}`, written through
`settings.set_value` like any project setting. **`look`** allows the service's read tools only —
names containing `search`, `get`, `list`, `read`, `fetch`, `view`; **`look_and_add`** also allows
`create` and `add`; **no level ever allows** `send`, `delete`, `remove`, `trash`, `share`,
`forward`, `reply` or `update`. With nothing allowed, a job runs exactly as Task 1 made it.
With something allowed, `_build` uses the mechanism Task 5's Step 0 chose.

- [ ] **Step 1: Write the failing tests** — `test_nothing_allowed_is_task_13_unchanged`,
      `test_look_passes_only_the_read_tools`, `test_look_and_add_never_passes_send_or_delete`,
      `test_one_project_allowing_drive_does_not_give_it_to_another`.
- [ ] **Step 2: Run them.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Verify live, once**: allow Google Drive *look* on the sandbox project and run one
      `explorer` dispatch asking it to name one file in her Drive; it must be able to, and a second
      project must not. One small request each, on her plan.
- [ ] **Step 6: Commit** `feat(connections): each project uses only what you allowed`

---

### Task 7: The Connected services page

**Files:**
- Create: `cockpit/templates/plain/services.html`
- Modify: `cockpit/views.py`, `cockpit/words.py`, `cockpit/templates/plain/base.html` (a link beside *What it uses*)
- Test: `tests/unit/test_plain_services.py`

As the mock-up (`.superpowers/mockups/phase-g-services.html`): three groups — **Through your
Claude account**, **Came with your plugins**, **Added by you** — each service with its state in
words and, for the chosen project, *Not used · May look · May look and add*. Services needing
sign-in sit in a folded list, *8 more that aren't signed in*.

**Adding a service:** an account service is added and signed in **on claude.ai** — the page links
to `https://claude.ai/settings/connectors` and says so; Taller never handles that sign-in. A
service from the catalogue is added with `claude mcp add`, after a confirmation that names the
maker and says *It will be able to act inside Taller's work on the projects you allow*.

**Searching:** the public registry, queried with her words, **known makers first**: results whose
name's publisher namespace matches `words.KNOWN_MAKERS` (Google, Microsoft, Atlassian, Notion,
Slack, Todoist, Linear, Figma, Cloudflare, Stripe, GitHub, Anthropic) are listed first and marked
*by <maker>*; the rest follow under *From other makers — check who made it before adding*.
A search that fails is one sentence.

- [ ] **Step 1: Write the failing tests** — `test_services_are_listed_in_three_groups_in_words`,
      `test_choosing_a_level_writes_the_project`, `test_adding_an_account_service_sends_her_to_claude_ai`,
      `test_known_makers_come_first_and_the_rest_are_marked`, `test_nothing_is_added_without_confirming`,
      `test_the_page_names_nothing_from_the_machine` (no `mcp`, no URLs, no prefixes).
- [ ] **Step 2: Run them.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cockpit): your connected services, in one place`

---

### Task 8: Telling her when something needs her

**Files:**
- Create: `src/taller/notify.py`
- Modify: `src/taller/tickets.py` (the moment a checkpoint turns pending, or a ticket stops), `src/taller/roles.py` (a `notifier` role), `cockpit/templates/plain/services.html`
- Test: `tests/unit/test_notify.py`

**Interfaces — produces:**

```python
CHANNELS = ("todoist", "calendar")
def configured() -> dict          # {"channel": str | None, "when": ["needs_you", "stopped"]}
def tell(project_name: str, ticket: Mapping, why: str) -> dict   # {"sent": bool, "problem": str}
```

On the services page, under **Tell me when something needs me**: *Add a task to my Todoist* or
*Put a note on my calendar*, off by default, with *when it needs me* and *when it stops* as two
ticks. When a ticket's checkpoint becomes pending or it is blocked, `tell` dispatches one
`notifier` job — `haiku`, low effort — allowed **exactly one tool** of the chosen service, with
the words fixed by `words.NOTICE`: *"Toolshed: 'The loans list doesn't match' is ready for
you to look at."* and a link to its page. The notifier never runs twice for the same moment
(recorded in `status.yml` as `notified: {checkpoint: timestamp}`), and a failure is recorded and
shown on the services page — it never blocks, retries or delays the work (Review Focus 7).
Gmail is not a channel: sending is not offered (Global Constraints).

- [ ] **Step 1: Write the failing tests** — `test_a_needs_you_moment_sends_one_notice`,
      `test_the_same_moment_is_never_told_twice`, `test_the_notifier_is_allowed_one_tool_only`,
      `test_a_failed_notice_is_recorded_and_the_work_carries_on`, `test_off_by_default`.
- [ ] **Step 2: Run them.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Verify live, once**: with Todoist chosen, one notice for a sandbox ticket; the task
      appears in her Todoist. She is told first that it will.
- [ ] **Step 6: Commit** `feat(notify): tell me when something needs me`

---

### Task 9: The proof — what it uses, and what it may reach

**Files:** Create `tests/acceptance/test_usage_and_services.py`

On an empty HOME with the stub `claude` and two projects: a ticket is run by the chief, and
*What it uses* names the model that did each job and says where that ticket's usage went; every
dispatch the stub saw carried `--strict-mcp-config` while no service was allowed; allowing a
service for one project gives it to that project's jobs only; a needs-you moment produces exactly
one notice through the stubbed service, and never a second; no plain page names the machine; and
`taller doctor` is still green.

- [ ] Write · run · whole suite green · commit `test(acceptance): what it uses, and what it may reach`

---

## Deferred, recorded rather than forgotten

| Item | Why not now |
|---|---|
| Spend and Health in plain words | Reading screens she has not asked for; they stay on `/board` until she says otherwise |
| Editing Taller's own shared rules from the plain front | They are written for the machine and shared by every project; `/board` keeps the editor |
| Emailing her when something needs her | Sending is the one thing a service could do that reaches other people if it goes wrong; Todoist and the calendar are hers alone |
| Making the explorer read less | 58% of ticket 0001 was the explorer re-reading the project about 70 times to decide which files a change touches. That is Taller's own design, and it deserves its own ticket - on Taller, now that Taller manages itself |
| The twelve onboarding questions restyled | They already read as plain language; the look follows once the front is settled |
| Taller's interface in Spanish | Her projects' interfaces are Spanish by her own rule; Taller's own has been English throughout, and switching it is a decision, not a detail |
| Notifications when something needs her | A page she leaves open refreshes itself; anything more is a new mechanism |
