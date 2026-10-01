# Phase G, first half — the plain front, her settings, and nothing published until she says Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Taller becomes usable by its owner, who is not an engineer: her projects and what she asked for, in her own words; what each project is, its rules and its look, which she can read and change; the work starting by itself; and nothing ever leaving her machine until she presses a button.

**This is the first half of Phase G** (her choice, 2026-09-29). The second half — *What it uses* and *Connected services* — is `2026-09-29-phase-g2-usage-and-services.md`.

**The look was agreed from two mock-ups before this plan was executed:** `.superpowers/mockups/phase-g-front.html` (screens 1-3) and `.superpowers/mockups/phase-g-settings.html` (screens 4-7). They are git-ignored on purpose: they carry her project's name and example content, and this repository is public. Where the words in a task and a mock-up differ, the mock-up wins.

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

1. **A finding whose rule id has no sentence yet** — a gate rule added later must never surface as `size.whatever` on her page; it shows its message and nothing machine-shaped. — Task 3.
2. **A project with no remote at all** — "publish" must say there is nothing to publish rather than offering a button that fails. — Task 7.
3. **A stopped ticket** — when the chief blocks, the plain page must say what stopped and what she can do, in a sentence, not show a gate's log. — Task 5.
4. **A brand guide that is not one** — a 40 MB scan, a Word file, a photo of a menu: refused or read, but always with a sentence, never a trace, and never a brand half-written. — Task 11.
5. **Publishing with no network, or a remote that refuses** — it says so plainly, the work is untouched, and pressing it again later works. — Task 7.
6. **Changing an answer about the project after she has written her own rules** — today `taller project brief` rewrites `product.md` and `never.md` from the answers and her additions vanish; they must survive. — Task 8.

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

### Task 1: Publishing is a decision, not a side effect

**Files:**
- Create: `src/taller/publishing.py`, `src/taller/commands/publish.py`
- Modify: `src/taller/config.py` (defaults), `src/taller/gitio.py`, `src/taller/cli.py`, `src/taller/doctor.py`
- Test: `tests/unit/test_publishing_held.py`

**Interfaces — produces:**

```python
# src/taller/publishing.py
def automatic(project: Path | str | None = None) -> bool     # setting `publish.automatic`, default False
def waiting(project: Path | str) -> dict
    # {"remote": str, "commits": [{"sha", "subject"}], "held": bool, "reason": str}
def send(project: Path | str) -> dict
    # {"sent": int, "remote": str, "problem": str}   - never raises on a refused push
HELD = "held"
```

`config.SHIPPED_DEFAULTS` gains `"publish": {"automatic": False}`. `gitio.SYNC_STATES` gains
`"held"`, meaning **a remote exists and the work has not been sent** — distinct from `local`
(no remote at all) and `pending` (tried to send, could not). `gitio._push` is called only when
`publishing.automatic(project)`; otherwise `commit_to_main` returns `held`. `doctor` reports
`held` as a **pass with a note** (it is her choice), and keeps reporting `pending` as a failure.

`taller publish [--path]` prints what would be sent, sends it, and says what happened.

- [ ] **Step 1: Write the failing tests**

```python
def test_by_default_nothing_is_pushed(project_with_remote):
    tickets.create(project, title="A thing", words="Do it.", kind="bug")
    assert tickets.load(project, 1)["sync"] == "held"
    assert commits_on(remote, "main") == before      # the remote never moved

def test_publishing_sends_everything_that_was_held(project_with_remote):
    waiting = publishing.waiting(project)
    assert len(waiting["commits"]) >= 1 and waiting["held"] is True
    sent = publishing.send(project)
    assert sent["problem"] == "" and sent["sent"] == len(waiting["commits"])
    assert tickets.load(project, 1)["sync"] == "ok"

def test_a_project_with_no_remote_has_nothing_to_publish(project):
    assert publishing.waiting(project) == {"remote": "", "commits": [], "held": False,
                                           "reason": "this project is only on this computer"}
    assert publishing.send(project)["problem"] == ""     # nothing to do is not a failure

def test_a_refused_push_says_so_and_changes_nothing(project_with_remote, monkeypatch):
    # the remote is unreachable
    sent = publishing.send(project)
    assert sent["problem"] and sent["sent"] == 0
    assert publishing.waiting(project)["held"] is True   # still waiting, still hers

def test_turning_it_on_restores_the_old_behaviour(project_with_remote):
    settings.set_value("publish.automatic", "true")
    tickets.create(project, title="Another", words="Do it.", kind="bug")
    assert tickets.load(project, 2)["sync"] == "ok"

def test_doctor_does_not_call_held_work_a_fault(project_with_remote):
    rows = [c for c in doctor.run_checks() if "publish" in c.name or "sync" in c.name]
    assert all(c.status != doctor.FAIL for c in rows)
```

- [ ] **Step 2: Run them** — `python -m pytest -q -p no:cacheprovider tests/unit/test_publishing_held.py`. Expected: FAIL, `No module named 'taller.publishing'`.
- [ ] **Step 3: Implement** `publishing.py`, the default, the `held` state in `gitio`, and `taller publish`.
- [ ] **Step 4: Run them.** Expected: PASS. Then `python -m pytest -q -p no:cacheprovider tests/unit -k "gitio or sync or doctor"` — Expected: PASS, or a ruling for each changed expectation.
- [ ] **Step 5: Commit** `feat(publishing): nothing leaves this machine until you say so`

---

### Task 2: ⑧ waits for publishing instead of pushing

**Files:**
- Modify: `src/taller/chief.py` (the `pr` stage), `src/taller/prs.py`
- Test: `tests/unit/test_chief_pr_held.py`

**Interfaces — consumes:** Task 1's `publishing.automatic`, `publishing.waiting`.

A pull request cannot exist without pushing a branch, so with publishing held, ⑧ **stops and
asks** rather than pushing: the ticket stays at ⑧ with `waiting_on: "publish"` and a sentence.
`prs.create` is not called at all — it must not be the thing that discovers the setting.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_pull_request_is_not_opened_behind_her_back(project_with_remote):
    # ticket at pr, publishing held
    assert chief_ran(project, 1)["stage"] == "pr"
    assert "publish" in tickets.load(project, 1)["waiting_on"]
    assert gh_calls() == []                      # nothing was pushed, nothing asked of GitHub

def test_publishing_then_running_opens_it(project_with_remote):
    publishing.send(project)
    assert chief_ran(project, 1)["pr"] == 7

def test_with_publishing_on_it_behaves_as_before(project_with_remote):
    settings.set_value("publish.automatic", "true")
    assert chief_ran(project, 1)["pr"] == 7
```

- [ ] **Step 2: Run them.** Expected: FAIL — ⑧ opens the pull request today.
- [ ] **Step 3: Implement** the guard at ⑧ and the waiting sentence.
- [ ] **Step 4: Run them**, then `python -m pytest -q -p no:cacheprovider tests/unit -k "chief or prs"`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(chief): a pull request waits for you to publish`

---

### Task 3: Her words

**Files:**
- Create: `cockpit/words.py`, `cockpit/plain.py`
- Test: `tests/unit/test_plain_words.py`

**Interfaces — produces:**

```python
# cockpit/words.py  - every word the plain front shows
STATES = {"working": "Working on it", "needs_you": "Needs you",
          "stopped": "Stopped", "done": "Done"}
DOING: dict[str, str]        # stage -> what it is doing now, a sentence
FINDINGS: dict[str, str]     # rule id -> a sentence about the finding
GROUPS = {"look": "Worth a look before you say yes", "small": "Small things"}

# cockpit/plain.py  - the machine's state, in those words. Pure; imports no Flask.
def state_of(ticket: Mapping) -> str                 # one of STATES' keys
def doing(ticket: Mapping) -> str                    # "Writing a plan for you to read"
def sentence(finding: Mapping) -> str                # a finding as one line, with the file
def what_it_did(project: Path, ticket: Mapping) -> dict
    # {"summary", "files": [{"name", "added", "removed"}], "more": int}
def things(project_name: str) -> list[dict]          # her things, newest first
def home() -> dict                                   # {"projects": [...], "needs_you": [...]}
def thing(project_name: str, ticket_id: int) -> dict
    # {"project", "id", "title", "asked", "state", "doing", "did", "look", "small",
    #  "stopped", "decide", "publish"}
```

`DOING`, one line per stage, exactly:

| stage | sentence |
|---|---|
| `intake` | Just asked for |
| `triage` | Looking at your project to see what this touches |
| `design` | Writing a plan for you to read |
| `build` | Making the change |
| `gates` | Checking its own work |
| `smoke` | Starting your app to see that it still runs |
| `review` | Ready for you to look at |
| `pr` | Getting it ready to publish |
| `staging` | Ready for you to try |
| `merge` | Putting it into your project |
| `release` | Ready to finish |
| `close` | Finished |

`FINDINGS`, one line for each of the 24 ids in `gates.RULES`, exactly:

| rule | sentence |
|---|---|
| `brand.hardcoded-color` | A colour was written straight into the page instead of using your brand's |
| `brand.hardcoded-font` | A typeface was written straight into the page instead of using your brand's |
| `constitution.commit-message-shape` | One of its saved notes is not written the way your project writes them |
| `constitution.layer-violation` | One part of the program reaches into another part it should not touch |
| `constitution.new-ui-literal` | Some wording was typed into the page instead of kept where your wording lives |
| `constitution.override-expired` | A rule you set aside for a while has run out, so it applies again |
| `constitution.override-not-permitted` | Something tried to set aside a rule that can never be set aside |
| `constitution.override-without-reason` | A rule was set aside with no reason written down |
| `constitution.resolved-snapshot-modified` | The copy of your rules inside this project was edited by hand |
| `constitution.resolved-snapshot-stale` | Your rules changed, and this project has not caught up yet |
| `constitution.root-markdown` | A new notes file was left at the top of your project |
| `constitution.single-use-script` | A one-off script was left behind in your project |
| `constitution.unknown-rule-id` | Your rules mention a check that does not exist |
| `size.duplicate-block` | The same lines appear in more than one place |
| `size.file-too-long` | One file is getting long |
| `size.function-too-long` | One piece of the program is getting long |
| `smoke.boot-failed` | Your app did not start |
| `smoke.not-rendered` | A page came up empty |
| `smoke.route-error` | A page returned an error |
| `smoke.timeout` | Your app took too long to start |
| `smoke.unmapped-template` | There is a page that nothing links to |
| `tests.coverage-below-minimum` | Less of your project is covered by tests than you asked for |
| `tests.error` | The tests could not run |
| `tests.failed` | Some tests did not pass |

`sentence()` appends the place when the finding has one — `"… — in static/css/app.css, line 12"` —
and for a rule with **no** entry in `FINDINGS` it falls back to the finding's own `message`,
never the id (Review Focus 1). `state_of` maps: a blocked ticket → `stopped`; a pending
checkpoint → `needs_you`; stage `close` or `outcome` set → `done`; anything else → `working`.
`look` holds the findings whose severity is `BLOCKER` or `HIGH`, `small` the rest — the words
"blocker" and "high" appear nowhere.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_rule_taller_can_report_has_a_sentence():
    assert set(words.FINDINGS) == set(gates.RULES)

def test_no_sentence_reads_like_a_machine():
    forbidden = ("gate", "verdict", "lane", "checkpoint", "blocker", "severity",
                 "branch", "commit", "sha", "sync", "worktree", "stage")
    for text in [*words.FINDINGS.values(), *words.DOING.values(), *words.STATES.values()]:
        assert not [w for w in forbidden if w in text.lower()]

def test_every_stage_says_what_it_is_doing():
    assert set(words.DOING) == set(tickets.STAGES)

def test_a_rule_with_no_sentence_shows_its_own_message():
    said = plain.sentence({"rule": "size.something-new", "severity": "MEDIUM",
                           "message": "Two files look the same.", "file": "", "line": 0})
    assert said == "Two files look the same."
    assert "size." not in said

def test_the_four_states(project):     # working / needs you / stopped / done
def test_a_finding_says_where_it_is(project):
    assert plain.sentence(finding).endswith("— in static/css/app.css, line 12")
```

- [ ] **Step 2: Run them.** Expected: FAIL, `No module named 'cockpit.words'`.
- [ ] **Step 3: Implement** `words.py` and `plain.py`.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cockpit): the machine's state, in her words`

---

### Task 4: The look, and the front page

**Files:**
- Create: `cockpit/static/plain.css`, `cockpit/templates/plain/base.html`, `cockpit/templates/plain/home.html`
- Modify: `cockpit/views.py` (the plain `/`; the old board moves to `/board`)
- Test: `tests/unit/test_plain_home.py`

**Interfaces — consumes:** Task 3's `plain.home()`.

**The look**, decided here so nothing is guessed:

- One column, `max-width: 46rem`, centred, `padding: 2rem 1.25rem`. Never a table.
- `--paper #faf9f7`, `--ink #1f1d1b`, `--muted #6b6560`, `--line #e7e3de`, `--working #1d4ed8`,
  `--needs-you #b45309`, `--done #15803d`, `--stopped #b91c1c`. Dark mode mirrors these under
  `@media (prefers-color-scheme: dark)`.
- System font stack; body `17px/1.55`; page title `1.75rem`; card title `1.125rem`; nothing
  below `0.9375rem` — she reads this, not a terminal.
- A card: `1px solid var(--line)`, `border-radius: 12px`, `padding: 1.25rem`, `margin-bottom: .75rem`,
  background white (`--card`). A state chip: a coloured dot and the word, `0.9375rem`, never a badge.
- Buttons: `min-height: 44px`, `padding: .7rem 1.1rem`, `border-radius: 10px`; the main one filled
  with `--ink`, the second outlined. One filled button per screen.
- Nothing hoverable that is not clickable; `:focus-visible` outlines everywhere.

**The page**, exactly:

```
My projects                                   [ Ask for something ]

Needs you
  "The loans list doesn't match"   Toolshed          →
  "Add a summary by week"            Toolshed          →

Toolshed                                    2 waiting · 1 working
  "Fix the export"                 · Working on it — making the change
  "The loans list doesn't match"  · Needs you — ready for you to look at
  "Add a summary by week"           · Needs you — a plan is ready to read
  3 finished things have not left this computer.   [ Publish them ]

Toolshed                                                   nothing yet
  Nothing asked for yet.                   [ Ask for something ]
```

- [ ] **Step 1: Write the failing tests**

```python
def test_the_front_page_is_her_projects_and_her_things(project, client):
    page = client.get("/").get_data(as_text=True)
    assert "My projects" in page and "The loans list" in page
    assert "Working on it" in page

def test_the_front_page_names_nothing_from_the_machine(project, client):
    page = client.get("/").get_data(as_text=True).lower()
    for word in ("lane", "gate", "verdict", "checkpoint", "intake", "triage",
                 "worktree", "sha", "sync", "①", "⑦"):
        assert word not in page

def test_what_needs_her_comes_first(project, client):
def test_a_project_with_nothing_in_it_says_so_and_offers_the_one_thing(project, client):
def test_forty_things_and_a_very_long_ask_still_render(project, client):
    # 40 tickets, one title of 400 characters
    assert answer.status_code == 200 and len(page) < 400_000

def test_the_detailed_board_is_still_there(project, client):
    assert client.get("/board").status_code == 200

def test_the_stylesheet_is_served_from_this_machine(client):
    assert client.get("/static/plain.css").status_code == 200
    assert "cdn" not in client.get("/").get_data(as_text=True).lower()
```

- [ ] **Step 2: Run them.** Expected: FAIL — `/` is the old board.
- [ ] **Step 3: Implement** the stylesheet, `plain/base.html`, `plain/home.html`, and the routes.
- [ ] **Step 4: Run them**, then `python -m pytest -q -p no:cacheprovider tests/unit/test_cockpit_board.py` with `/board` — Expected: PASS (update its paths; ledger the change).
- [ ] **Step 5: Commit** `feat(cockpit): a front page in plain words`

---

### Task 5: One thing, and the two buttons

**Files:**
- Create: `cockpit/templates/plain/thing.html`
- Modify: `cockpit/views.py`, `src/taller/roles.py` (the summariser's `files` key), `src/taller/agents/summariser.md`
- Test: `tests/unit/test_plain_thing.py`

**Interfaces — consumes:** Task 3's `plain.thing()`; part one's `check_token`, `tickets.approve`,
`tickets.reject`, `runs.start`.

**The page**, exactly:

```
"The loans list doesn't match"                          Needs you

You asked for
  The loans list doesn't match what's on the shelves. It should come
  from the returns book.

What it did
  The list now comes from the returns book instead of the loan
  slips. Three files changed.
  · Keeping the loans list          +48 −12
  · The loans page       +6
  · Its tests                     +31
  [ Show me the plan it followed ]

Worth a look before you say yes
  · A colour was written straight into the page — in static/css/app.css, line 12

Small things
  · One file is getting long — loans/ledger.py

  [ Yes, carry on ]        [ No, change it ]
```

**Files are named in words, not paths.** `loans/ledger.py` means nothing to her; *Keeping the loans
list* does. The summariser already runs at ⑦ and writes the summary shown under *What it did*;
its answer gains `files: {path: "a few plain words"}`, and `plain.what_it_did` uses that name,
falling back to the file's own name without its folder or extension (`ledger`) when the
summariser gave none. The path itself appears only on `/board`.

"No, change it" opens a box with one label — *What should be different?* — and the same button; an empty
reason is refused with a sentence (part one's library refusal). When the ticket is **stopped**,
the two buttons are replaced by what stopped it as one sentence plus *Try again*, which calls
`tickets.resume` (Review Focus 3). When it is **working**, there are no buttons: the page shows
what it is doing and refreshes itself every four seconds, as part one's run panel does.

- [ ] **Step 1: Write the failing tests**

```python
def test_it_says_what_she_asked_for_and_what_it_did(project, client)
def test_files_are_named_in_words_when_the_summariser_named_them(project, client):
    assert "Keeping the loans list" in page and "loans/ledger.py" not in page
def test_a_file_the_summariser_did_not_name_falls_back_to_its_own_name(project, client):
    assert "ledger" in page and "loans/" not in page
def test_findings_are_sentences_not_rule_ids(project, client):
    assert "brand.hardcoded-color" not in page
    assert "A colour was written straight into the page" in page
def test_saying_yes_carries_it_on(project, client, started)      # approve + a run starts
def test_saying_no_needs_words_and_records_them(project, client)
def test_a_stopped_thing_says_what_stopped_and_offers_to_try_again(project, client)
def test_while_it_works_there_is_nothing_to_press(project, client)
def test_a_thing_that_is_not_hers_is_a_plain_not_found(project, client)
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `thing.html`, `GET /thing/<project>/<id>`, and the two posts (reusing
      part one's `views._write`), plus `POST …/try-again`.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cockpit): one thing, and two buttons`

---

### Task 6: Asking for something, and the work starting by itself

**Files:**
- Create: `cockpit/templates/plain/ask.html`
- Modify: `cockpit/views.py`
- Test: `tests/unit/test_plain_ask.py`

**Interfaces — consumes:** `tickets.create`, `runs.start` (part one).

The form is a project picker, one big box — *What do you want? Say it however you like.* — and one
button, *Ask for it*. No kind, no lane, no title: `tickets.create` is called with `kind="feature"`
and a title taken from her first line (trimmed to `tickets.TITLE_MAX`), and the chief renames it at
① intake as it already does. Creating it starts `taller ticket run` in its own process immediately,
and the browser lands on that thing's page, already working.

- [ ] **Step 1: Write the failing tests**

```python
def test_asking_for_something_makes_it_and_starts_it(project, client, started):
    answer = client.post("/ask", data={..., "project": "toolshed",
                                       "words": "The loans list doesn't match."},
                         follow_redirects=True)
    assert tickets.load(project, 1)["title"]
    assert started and started[0][-4:] == ["run", "1", "--path", str(project)]
    assert "Working on it" in answer.get_data(as_text=True)

def test_an_empty_ask_is_refused_without_losing_her_words(project, client)
def test_the_title_is_her_first_line(project, client)
def test_asking_needs_the_token(project, client)
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `ask.html`, `GET /ask`, `POST /ask`.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cockpit): ask for something, and it starts`

---

### Task 7: Publishing, from the page

**Files:**
- Modify: `cockpit/plain.py`, `cockpit/templates/plain/home.html`, `cockpit/views.py`
- Test: `tests/unit/test_plain_publish.py`

**Interfaces — consumes:** Task 1's `publishing.waiting`, `publishing.send`.

Each project's card ends with one line and one button when something is held:
*"3 finished things have not left this computer."* → **Publish them**. A project with no remote says
*"This project is only on this computer."* and offers no button (Review Focus 2). A refused push
becomes one sentence on the page and the work stays held (Review Focus 5).

- [ ] **Step 1: Write the failing tests**

```python
def test_the_page_says_what_has_not_left_this_computer(project_with_remote, client)
def test_pressing_publish_sends_it(project_with_remote, client)
def test_a_project_with_no_remote_offers_no_button(project, client):
    assert "only on this computer" in page and "Publish them" not in page
def test_a_refused_push_is_one_sentence_and_nothing_is_lost(project_with_remote, client, monkeypatch)
def test_publishing_needs_the_token(project_with_remote, client)
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** the line, the button, and `POST /publish/<project>`.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cockpit): publish when you say so`

---

### Task 8: Her own rules survive a change to what the project is

**Files:**
- Create: `src/taller/own_rules.py`
- Modify: `src/taller/scaffold.py` (`product_md`, `never_md`), `src/taller/commands/project.py:195-205`
- Test: `tests/unit/test_own_rules.py`

**The defect this fixes, found while designing:** `taller project brief` regenerates
`.taller/constitution/product.md` and `never.md` wholesale from the twelve answers
(`commands/project.py:199-200`). Anything written there by hand — or by part two's Rules
screen — is lost the next time one answer changes. A page that invites her to write rules
cannot sit on top of that.

**Interfaces — produces:**

```python
# src/taller/own_rules.py
OWN_HEADING = "## Your own rules"            # the section the answers never touch

def read(project: Path | str) -> dict        # {"always": [Rule], "never": [Rule]}
    # Rule = {"text": str, "why": str, "added": str}   (added: ISO date)
def add(project: Path | str, kind: str, text: str, why: str = "") -> list[str]
def remove(project: Path | str, kind: str, index: int, why: str) -> list[str]
```

`always` rules live under `OWN_HEADING` in `product.md`; `never` rules under the same heading
in `never.md`. Each rule is one list line — `- <text>` — followed by an indented
`  <why> (added YYYY-MM-DD)` when a reason was given. `scaffold.product_md` and
`scaffold.never_md` gain `existing: str | None = None` and carry everything from `OWN_HEADING`
to the end of the file over unchanged. `add` and `remove` are amendments: under the project
lock, on `main` only (refused off `main` exactly as `rules.save` is), committed as
`amend: <why or the rule itself>`, then `generated.refresh(project)`. `remove` requires a reason.

- [ ] **Step 1: Write the failing tests**

```python
def test_changing_an_answer_keeps_her_own_rules(project):
    own_rules.add(project, "always", "Take the list from the returns book.",
                  "The slips are often late.")
    change_answer(project, "must_never_break", "The daily totals.")       # the brief path
    assert [r["text"] for r in own_rules.read(project)["always"]] == \
        ["Take the list from the returns book."]
    assert "The daily totals." in product_md(project)

def test_a_rule_reaches_the_rules_the_gates_read(project):
    own_rules.add(project, "never", "Show a neighbour's phone number.")
    assert "Show a neighbour's phone number." in resolved_json(project)

def test_removing_a_rule_needs_a_reason(project)
def test_a_rule_is_refused_while_the_project_is_on_a_ticket_branch(project)
def test_a_rule_is_kept_with_why_and_when(project):
    rule = own_rules.read(project)["always"][0]
    assert rule["why"] == "The slips are often late." and rule["added"]
```

- [ ] **Step 2: Run them.** Expected: FAIL, `No module named 'taller.own_rules'`.
- [ ] **Step 3: Implement** `own_rules.py` and the carry-over in `scaffold`.
- [ ] **Step 4: Run them**, then `python -m pytest -q -p no:cacheprovider tests/unit -k "scaffold or brief or onboarding"`. Expected: PASS.
- [ ] **Step 5: Commit** `fix(rules): your own rules survive a change to what the project is`

---

### Task 9: About it

**Files:**
- Create: `cockpit/project_settings.py`, `cockpit/templates/plain/settings/base.html`, `cockpit/templates/plain/settings/about.html`
- Modify: `cockpit/views.py`, `cockpit/words.py`
- Test: `tests/unit/test_plain_settings_about.py`

**Interfaces — produces:**

```python
# cockpit/project_settings.py
def about(project_name: str) -> dict       # {"project", "cards": [{"key", "question", "answer"}]}
def change_answer(project_name: str, key: str, raw: str | list[str]) -> dict   # {"ok", "problem"}
```

The four tabs — **About it**, **Its rules**, **Look and feel**, **Choices** — share one
`settings/base.html`; a project's name on the front page links to it. `about` shows the answers
as five cards, exactly as the settings mock-up's screen 4 groups them:

| Card | From answers |
|---|---|
| What it does | `what_it_does` |
| What would be a disaster if it broke | `must_never_break` |
| What it should never turn into | `what_it_is_not` |
| What it keeps | `stores`, `sensitive_data` (as *Money or personal details: yes — every change touching them is checked twice.*) |
| Who uses it, and where | `users`, `reach`, `phone`, as one sentence |

`change_answer` validates through `onboarding.ask_one` with an answer sheet — the same call the
interview uses (part two) — then takes the same path as `taller project brief`: rewrite
`brief.yml`, `product.md` and `never.md` (carrying her own rules over, Task 8), commit, refresh.
The profile, the brand and where it runs are **not** on this page: the first two change what
the project is built from, and are Look and feel's and a deliberate re-adoption's business.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_answers_are_shown_as_she_gave_them(project, client)
def test_changing_one_answer_rewrites_the_rules_it_feeds(project, client)
def test_a_refused_answer_says_why_and_changes_nothing(project, client)
def test_her_own_rules_survive_changing_an_answer_from_the_page(project, client)
def test_the_settings_pages_name_nothing_from_the_machine(project, client)   # all four tabs
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `about`, `change_answer`, the tab frame and `about.html`.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cockpit): what the project is, in your words`

---

### Task 10: Its rules

**Files:**
- Create: `cockpit/templates/plain/settings/rules.html`
- Modify: `cockpit/project_settings.py`, `cockpit/words.py`, `cockpit/views.py`
- Test: `tests/unit/test_plain_settings_rules.py`

**Interfaces — consumes:** Task 8's `own_rules`; `constitution.resolve`. **Produces:**

```python
def rules(project_name: str) -> dict
    # {"always": [Rule], "never": [Rule], "exceptions": [{"text", "until", "expired"}],
    #  "practice": [str], "practice_more": int}
```

Four sections, as the mock-up's screen 5 shows them: **It must always**, **It must never** (her
rules, each with an *Add* box and a remove link that asks why), **Exceptions you've allowed**
(the project's overrides in words: the rule's `FINDINGS` sentence, the reason, and *Until <date>
— then the rule applies again*, amber when it has passed), and **Rules that come with Taller**
(*Good practice for every project. You don't need to look after these.*).

That last section is **one line per hub rule file** in force for the project, from a new table
in `words.py`:

| Module | Line |
|---|---|
| `never` | Never save a password or key in the project, and never make a check easier just so it passes |
| `security/minimal` | Keep anything secret out of the project and out of its logs |
| `security/web-app` | Every page that changes something checks who is asking, and whether they may |
| `conventions/python` | The program is written the same way throughout, so any part can be read |
| `conventions/js` | The code that runs in the browser is written the same way throughout |
| `stack/flask-sqlite` | It is built as a web app with its own small database |
| `stack/python-packaged` | It is built as a program you install and run |
| `ux/bootstrap` | Every screen uses your brand's colours and fonts, never ones typed in, and works without a mouse |

A module missing from the table shows its file's own `> ` summary line — never its id.
Hub rules are not editable here: they are shared by every project and written for the machine;
the page says so, and links to `/board`'s Rules screen for the day she needs it.

- [ ] **Step 1: Write the failing tests**

```python
def test_her_rules_are_listed_under_always_and_never(project, client)
def test_adding_a_rule_from_the_page_records_it_with_its_reason(project, client)
def test_removing_a_rule_asks_why(project, client)
def test_an_exception_says_until_when_in_words(project, client):
    assert "Until 31 December" in page and "size.file-too-long" not in page
def test_every_rule_file_taller_ships_has_a_plain_line():
    assert set(words.PRACTICE) >= set(catalogue_module_ids())
def test_taller_rules_are_shown_but_not_offered_for_editing(project, client)
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `rules`, the two posts, `rules.html` and `words.PRACTICE`.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cockpit): the rules, in your words`

---

### Task 11: Look and feel

**Files:**
- Create: `cockpit/templates/plain/settings/look.html`
- Modify: `cockpit/project_settings.py`, `cockpit/views.py`, `src/taller/brands.py` (a `read` that returns tokens and prose)
- Test: `tests/unit/test_plain_settings_look.py`

**Interfaces — consumes:** `brands.list_brands`, `brands.write`, `brands.from_pdf`,
`brands.from_image`, `brands.from_css`, `brands.propose_tokens`, `generated.refresh_affected`.
**Produces:**

```python
# src/taller/brands.py
def read(slug: str) -> dict        # {"slug", "tokens": {name: value}, "prose": str}

# cockpit/project_settings.py
def look(project_name: str) -> dict
    # {"brand": {...} | None, "swatches": [{"label", "value"}], "fonts": [{"label", "family"}],
    #  "prose", "shared_with": [str], "choices": [str]}
def use_brand(project_name: str, slug: str) -> list[str]
def change_brand(slug: str, tokens: Mapping[str, str], prose: str) -> list[str]
def propose_from(upload_path: Path, filename: str) -> dict     # {"tokens", "prose", "problem"}
UPLOAD_MAX = 20 * 1024 * 1024
UPLOAD_KINDS = (".pdf", ".png", ".jpg", ".jpeg", ".css")
```

As the mock-up's screen 6: the brand in use shown as **swatches** labelled in words (*Main*,
*Accent*, *Background*, *Text*, from `--color-primary`, `--color-accent`, `--color-background`,
`--color-text`; any other colour token as *Other*), each typeface as a **sample sentence set in
that face** with *Headings — Georgia* under it, and the brand's own prose under **In words**.
*Change a colour or typeface* opens colour pickers and font fields and saves through
`brands.write(replace=True)` and `generated.refresh_affected(brand=slug)`. When the brand is
used by other projects the page says so first — *This brand is also used by Boathouse.
Changing it changes both.* — in the amber note. *Use another* lists the hub's brands and `None`.

*Drop your brand guide here* accepts one file of `UPLOAD_KINDS` up to `UPLOAD_MAX`, reads it with
the matching `brands.from_*`, and opens the same edit form **pre-filled with the proposal** — it
never writes a brand until she saves (Review Focus 4). The upload is kept in the runtime
directory, never in the hub or the project, and deleted once the brand is saved or abandoned.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_brand_is_shown_as_colours_and_type_not_tokens(project_with_brand, client):
    assert "Main" in page and "--color-primary" not in page
def test_changing_a_colour_reaches_every_project_that_uses_it(project_with_brand, client)
def test_a_shared_brand_says_who_else_it_changes(two_projects_one_brand, client)
def test_a_brand_guide_is_read_into_a_proposal_she_confirms(project, client)
    # a small PDF fixture: tokens proposed, nothing written until the save
def test_a_file_that_is_not_a_brand_guide_is_refused_with_a_sentence(project, client)
def test_a_file_that_is_too_big_is_refused_before_it_is_read(project, client)
def test_nothing_is_written_until_she_saves(project, client)
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `brands.read`, `look`, the upload, the edit form and `look.html`.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cockpit): the look, as colours and type`

---

### Task 12: Choices

**Files:**
- Create: `cockpit/templates/plain/settings/choices.html`
- Modify: `cockpit/project_settings.py`, `cockpit/views.py`, `src/taller/config.py` (the `budget` default)
- Test: `tests/unit/test_plain_settings_choices.py`

**Interfaces — consumes:** `settings.set_value` (part two), Task 1's `publish.automatic`.
**Produces:** `def choices(project_name: str) -> dict`, `def choose(project_name: str, key: str, value: str) -> list[str]`.

Four choices, as the mock-up's screen 7, each written to **the project's own layer** through
`settings.set_value(..., project)`:

| Choice | Options | Writes |
|---|---|---|
| Publish on its own | a switch, off by default | `publish.automatic` |
| How much one piece of work may use | Little · Normal · A lot | `budget.per_ticket_warn` / `per_ticket_stop`: 500 000 / 1 500 000 · 1 200 000 / 4 000 000 · 3 000 000 / 10 000 000 |
| Tries before it asks you | Once · Twice · Three times | `thresholds.max_fix_rounds`: 1 · 2 · 3 |
| Language of the project's screens | Español · English | `language.ui`: `es` · `en` |

**The shipped `budget` default becomes *Normal* — 1 200 000 / 4 000 000 — in this task**, so a
project nobody has touched lights *Normal* rather than *Your own setting*. The old 400 000 was set
before any real ticket ran; Taller's own ticket 0001 crossed it just writing a plan. The numbers
are provisional and `config.py` says so: revisit once ten real tickets are recorded.

A value that matches none of the options (set by hand, or in a terminal) shows as *Your own
setting* with no option lit, rather than lighting the wrong one. *Everything else, for when
something goes wrong ›* links to `/board`'s Settings screen.

- [ ] **Step 1: Write the failing tests**

```python
def test_each_choice_shows_what_is_in_force(project, client)
def test_choosing_writes_the_project_layer_only(project, client)
def test_a_hand_set_value_shows_as_her_own_setting(project, client)
def test_publishing_on_its_own_is_off_until_she_turns_it_on(project, client)
def test_an_untouched_project_is_normal(project, client)
def test_the_shipped_warning_line_is_above_what_a_plan_alone_costs()
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `choices`, `choose` and `choices.html`.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(cockpit): the choices that matter, and nothing else`

---

### Task 13: The proof — asked for, worked on, decided and published, in plain words

**Files:** Create `tests/acceptance/test_plain_flow.py`

On an empty HOME with the stub `claude` and a real project with a remote: she asks for something
on `/ask`; the work starts by itself and the front page shows it working; the chief carries it to
the review checkpoint; her page shows what it did and at least one finding **as a sentence**; she
says yes; the thing reaches done; nothing has reached the remote until she presses Publish, and
after she does, the remote has it. Along the way she adds an *always* rule and changes one answer
on About it, and the rule survives; she drops a small PDF brand guide and saves the proposal; she
turns *Tries before it asks you* to *Once* and the project's own settings say 1. Throughout,
assert that no plain page contains any of the forbidden words, and that `taller doctor` is still
green.

- [ ] Write · run · whole suite green · commit `test(acceptance): asked for, worked on, decided and published`

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
