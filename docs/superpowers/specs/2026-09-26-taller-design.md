# Taller — Design Specification

**Date:** 2026-09-26
**Status:** Approved by owner (design phase complete)
**Owner:** Catia Schubert
**Pilot project:** `C:\Users\catia\cont` (payment-reconciliation)

---

## 0. Document scope and how to read it

This is the **system architecture specification** for Taller: a development
environment that wraps Claude Code so that one orchestrating agent holds project
context and delegates work to specialist agents, through quality gates, under
owner approval, with GitHub as the system of record.

The system has six phases (A–F, section 10). All six are specified here because
they share one contract — the constitution format, the ticket format, and the
model roster. The cockpit cannot be designed without knowing the ticket format;
the gates cannot be designed without knowing the constitution layout. Splitting
the specification would have produced six documents that contradict each other.

**Implementation is not planned here.** Each phase gets its own implementation
plan, written separately, in the order given in section 10. The first plan to be
written covers **Phase A only**.

**Language:** this document, all code, identifiers, comments, and commit messages
are in English. Application UI strings are in Spanish. This follows the owner's
existing convention.

---

## 1. Problem statement

The owner runs several production Flask applications for a hotel business and
builds them with Claude Code. Four concrete problems, measured on 2026-09-26:

### 1.1 Context is re-declared per project

```
8 CLAUDE.md files across programas/ and cont/ .... 143,487 chars ≈ 36,000 tokens
Front office/CLAUDE.md ............................. 9,466 chars ┐ byte-identical
Front-office-modules/CLAUDE.md ..................... 9,466 chars ┘
PuroBeachClub/CLAUDE.md ........................... 27,406 chars ≈  7,000 tokens
PuroBeachClub/context/*.md (3 files) .............. 64,388 chars ≈ 16,000 tokens
```

`PuroBeachClub/CLAUDE.md` is loaded in full at the start of every session and
into every subagent that reads it — roughly 7,000 tokens of preamble before the
owner types a word, and ~23,000 if an agent also reads `context/`. A CSS fix
loads the security policy. A database migration loads the brand rules.

### 1.2 Review infrastructure is copied, not shared

`code-review/`, `security-review/` and `design-review/` directories are
duplicated across HK, PuroBeach, PuroBeachClub, cont, and archive/Vouchers.
The same agent definitions exist in five or six places and drift independently.

### 1.3 Sessions have no memory, so work has no home

The `PuroBeachClub` repository root contains 40+ ad-hoc planning documents
(`PHASE4_CHECKPOINT.md`, `SESSION_SUMMARY.md`, `REFACTORING_PLAN.md`,
`REFACTORING_PLAN_ORIGINAL.md`, `CONSOLIDATED_REFACTORING_PLAN.md`, …) and
~60 single-use scripts (`fix_*.py`, `check_*.py`, `debug_*.py`). These are the
artefacts of each session inventing its own filing system because no shared one
exists.

### 1.4 Rules exist but nothing enforces them

`cont/static/css/admin.css` defines seven design tokens
(`--app-primary`, `--app-primary-dark`, `--app-accent`, `--app-success`,
`--app-warning`, `--app-danger`, `--app-bg-soft`). `cont/templates/` nonetheless
contains **26 hardcoded hex values**, including `#dc3545`, `#198754` and
`#ffc107` — which are already `--app-danger`, `--app-success` and
`--app-warning`. The convention is documented and bypassed.

### 1.5 No staging environment

Zero occurrences of "staging" across the repositories. Deployment is Docker
Compose (`web` + Caddy) to a private Linux server reachable over LAN and
Tailscale. Changes go from a branch to production with no intermediate place to
exercise them.

---

## 2. Goals and non-goals

### Goals

| # | Goal | Measured by |
|---|---|---|
| G1 | Cut always-loaded context | `cont` preamble ≤ 800 tokens (from ~7,000) |
| G2 | One orchestrator the owner talks to | Owner states intent once per ticket; no re-declaration of project facts |
| G3 | Shared rules, declared once | Front office + Front-office-modules local constitutions each < 2,000 chars |
| G4 | Enforced conventions | 0 hardcoded hex outside brand token files in `cont/templates/` |
| G5 | Work survives session death | Any ticket resumable from disk after a killed session |
| G6 | Visible cost | Every ticket records token spend by model tier |
| G7 | Owner keeps final control | 4 explicit approval checkpoints; nothing reaches production unapproved |
| G8 | Uniform across projects | Identical `.taller/` shape, stages, ticket format, and commands regardless of stack or brand |

### Non-goals

- **Not a replacement for superpowers.** Superpowers remains the brainstorm →
  plan → execute → verify engine. Taller adds what it lacks.
- **Not a persistent daemon.** See section 3.1.
- **Not multi-user.** Single operator. No auth in the cockpit; it binds to
  `127.0.0.1`.
- **Not a Spec Kit installation.** Ideas adopted (see section 11), toolchain not.
- **Not a refactor of existing applications.** Taller may *generate tickets* that
  clean up `PuroBeachClub`; it does not perform that cleanup as part of its own
  construction.

---

## 3. Architecture

### 3.1 The orchestrator, honestly

Claude Code has no persistent process. There is no agent that stays awake
between sessions holding project knowledge. Taller therefore does not provide an
orchestrator that *stays* briefed; it provides one that **arrives** briefed, in
~500 tokens, every session. Three mechanisms:

**Automatic arrival.** A `SessionStart` hook injects the chief's routing
instructions plus `00-index.md`. The owner never invokes the chief. (The owner
already runs `Notification`, `Stop` and `SubagentStop` hooks, so this is
consistent with the existing configuration.)

**State on disk, not in the conversation.** The constitution is what the project
*is*; the ticket folder is what is *happening*. Both are files in the repository.
Context compaction, a crashed session, or a closed laptop lose nothing. The
conversation is not the memory — the repository is.

**Load by need.** `00-index.md` is a routing map, not content:

| Work touches | Slices loaded |
|---|---|
| Template or CSS | `ux.md`, `brand.md`, brand `tokens.css` |
| Route or query | `architecture.md`, `security.md` |
| New feature | `product.md`, `architecture.md`, `conventions.md` |
| Money or auth (always) | `security.md`, `never.md` |

### 3.2 Three artifacts

```
programas/taller/          ① THE PLUGIN — the machinery.
                              Generic; contains no hotel- or brand-specific
                              knowledge. Shareable.

~/.taller/                 ② THE HUB — the owner's rules, brands, registry.
                              Its own git repository.

<project>/.taller/         ③ PER PROJECT — only what differs from the hub.
```

### 3.3 Layer responsibilities

| Layer | Provided by |
|---|---|
| Brainstorm → plan → execute → verify | superpowers (soft dependency, section 3.4) |
| Constitution, chief, routing, gates, tickets, cockpit | Taller |
| Issues, pull requests, CI, branch protection | GitHub via `gh` CLI |

The GitHub MCP server currently fails authentication (HTTP 401, stale token).
Taller uses the `gh` CLI, which is authenticated as `menfistoo` and working. The
design has no dependency on the GitHub MCP server.

### 3.4 Dependencies

| Dependency | Kind | Behaviour if absent |
|---|---|---|
| Claude Code | hard | Taller is a Claude Code plugin |
| Python 3.11+ | hard | Gate scripts and cockpit are Python |
| `gh` CLI, authenticated | hard for D/F | Ticket mirroring and PR stages fail with a clear error; local stages still work |
| superpowers | **soft** | Taller falls back to its own minimal plan step |
| Docker Compose | hard for staging only | Staging stage is skipped with a clear message |

Superpowers is a soft dependency so that the plugin remains standalone and
transferable.

---

## 4. The hub

```
~/.taller/                         git repository
├── projects.json                  registry: path, profile, brand, last seen
├── brands/
│   ├── purobeach/
│   │   ├── tokens.css             THE source of truth for colours + fonts
│   │   ├── brand.md               which token to use when (names, never values)
│   │   └── assets/                logo, favicon, fonts, images
│   └── <slug>/                    same shape, always
├── modules/                       shared constitution pieces, each optional
│   ├── stack/flask-sqlite.md      stack/static-js.md      stack/python-app.md
│   ├── security/web-app.md        security/minimal.md
│   ├── language/es-ui.md
│   └── conventions/python.md      conventions/js.md
├── profiles/                      named bundles, so onboarding is one choice
│   ├── flask-hotel.yml
│   ├── static-tool.yml
│   └── python-app.yml
└── templates/new-project/         stack skeletons
```

### 4.1 Profiles

A profile names the modules a project inherits and its default brand.

```yaml
# ~/.taller/profiles/flask-hotel.yml
name: flask-hotel
description: Flask + SQLite WAL + Jinja2 + Bootstrap 5 + Docker + Caddy
modules:
  - stack/flask-sqlite
  - security/web-app
  - language/es-ui
  - conventions/python
  - conventions/js
brand: purobeach
```

```yaml
# ~/.taller/profiles/python-app.yml
name: python-app
description: Packaged Python desktop application (PyInstaller)
modules:
  - stack/python-app
  - security/minimal
  - conventions/python
brand: none
```

The three initial profiles map to the owner's three existing project shapes:

| Profile | Existing projects |
|---|---|
| `flask-hotel` | cont, PuroBeachClub, HK, SSTT, Front office, Front-office-modules |
| `static-tool` | Creador de precios (static HTML/JS + Python helper, own `logo.png`) |
| `python-app` | wisper (PyInstaller desktop app, no UI) |

**YAGNI constraint:** no module is created until **two** projects need it. No
fourth profile until a real project requires one. This layer is indirection and
will become a maintenance burden if allowed to grow speculatively.

### 4.2 Brands

A brand is a folder. One brand serves many projects; a project has exactly one
brand, or `none`. Colour and font **values** exist only in
`brands/<slug>/tokens.css`. `brand.md` states intent and which token applies
where, by name.

`taller brand new <slug>` is guided and offers three starting points:

| Start from | Mechanism |
|---|---|
| Existing CSS | Reads `--*` custom properties from a named file and proposes them as the palette. `cont/static/css/admin.css` yields 7. |
| A logo image | Extracts dominant colours from e.g. `Creador de precios/logo.png` and proposes a palette. |
| Scratch | Guided: primary, accent, semantic (success/warning/danger), surfaces, typography, spacing scale. |

It then collects typography and assets, writes `tokens.css` and `brand.md`, and
renders a **swatch page** (a standalone HTML file opened locally) showing the
palette, type scale and assets, so the brand is reviewed visually rather than as
a list of hex codes.

### 4.3 Inheritance and resolution

A project inherits its profile's modules. `<project>/.taller/constitution/overrides.md`
may override any inherited rule, but **only with a written reason**. Gates
validate against the resolved set — never a single layer.

`~/.taller/` is a git repository because one edit can affect six projects.
Amendments therefore have history and can be reverted. Each gate verdict records
the hub commit SHA it validated against.

**Conflict rule:** project overrides hub. An override without a reason is itself
a constitution-gate violation.

---

## 5. Per-project layout

```
<project>/
├── CLAUDE.md                      stub: points at .taller/constitution/00-index.md
└── .taller/
    ├── taller.yml                 models, gates, thresholds, budget
    ├── constitution/
    │   ├── 00-index.md            ~40 lines. ALWAYS loaded. Map + routing table.
    │   ├── product.md             what this does, who uses it, what must never break
    │   ├── architecture.md        this project's layers and dependency rules
    │   └── overrides.md           deviations from the hub, each with a reason
    └── work/
        └── NNNN-slug/             tickets
```

`product.md` and `architecture.md` are always local — they cannot be inherited,
because they are what makes the project itself. Everything else comes from the
hub unless overridden.

### 5.1 taller.yml

```yaml
model_aliases:                # the ONLY place a model name appears
  thinker:  opus
  worker:   sonnet
  cheap:    haiku
  creative: fable             # untested; unassigned by decision

models:
  architect:         thinker
  implementer:       worker
  fixer:             worker
  gate_security:     thinker
  gate_quality:      worker
  gate_ux:           worker
  gate_constitution: cheap
  explorer:          cheap
  scribe:            cheap
  summariser:        cheap

effort:
  architect: high
  gates:     medium
  scribe:    low

fallback: worker              # unreachable model degrades, never crashes

budget:
  per_ticket_warn:  150000    # warn the owner
  per_ticket_stop:  400000    # stop and ask

thresholds:
  max_file_lines:     800
  max_function_lines: 80
  max_fix_rounds:     2
```

Two layers of indirection mean a new model release is a one-line change, not
thirteen. `fallback` means a model name the account cannot reach degrades to
`worker` rather than failing mid-ticket.

---

## 6. Model roster

| Agent | Alias | Rationale |
|---|---|---|
| Chief (owner's own session) | `worker` daily, `thinker` for design sessions | Routing is low-judgement work. Escalate only when architecting. |
| Scribe | `cheap` | Transcribes the owner's words into `ticket.md` |
| Explorer | `cheap` | Locates files, reports paths. High volume, low judgement. |
| Architect | `thinker` | The one place to spend. A bad plan costs more than the model. |
| Implementer | `worker` | Writes code |
| Fixer | `worker` | Applies findings already reasoned about by a gate |
| Constitution gate | `cheap` + linter | Rules are mechanical; the linter does the real work |
| Size gate | **none — Python** | Free |
| Tests gate | **none — Python** | Free |
| Security gate | `thinker` | A missed `@permission_required` is liability. Owner's explicit decision. |
| Code quality gate | `worker` | Runs often; sufficient |
| UX gate | `worker` | Checks conventions, does not invent them |
| Summariser | `cheap` | Condenses verdicts for the approval view |

**Model availability.** The set of available models cannot be enumerated from
the CLI (`--model` accepts an alias or a full name and does not list options).
`taller models probe` sends a one-token request to each candidate (`opus`,
`sonnet`, `haiku`, `fable`, plus any name the owner adds) and reports which are
reachable, with latency. This replaces guessing and is re-run whenever a new
model ships.

**Fable 5.1** is deliberately unassigned. It is available as `fable` and is a
plausible candidate for the UX gate, but there is no evidence it outperforms
`worker` there. Assigning it on speculation would cost a debugging cycle.

---

## 7. The ticket

### 7.1 On disk

```
.taller/work/0043-date-filter/
├── ticket.md          the owner's words, verbatim, plus the classification
├── status.yml         machine state — read by the cockpit and the next session
├── plan.md            full lane only
├── gates/             one verdict file per gate that ran
└── notes.md           decisions and WHY
```

```yaml
# status.yml
id: 43
slug: date-filter
title: Filtro de fecha por hora en Caja
kind: bug                  # bug | feature | refactor | question | idea
lane: fast                 # fast | full
stage: review
branch: ticket/0043-date-filter
issue: 87
hub_sha: a3f9c21
created: 2026-09-26T10:14:00
gates: [constitution, quality, tests]
verdicts:
  constitution: pass
  quality: pass (2 low)
  tests: pass
fix_rounds: 1
checkpoints:
  design:  skipped
  review:  pending
  staging: n/a
  release: pending
spend:
  cheap:   12400
  worker:  48200
  thinker: 0
```

### 7.2 Ticket creation and branch visibility

If ticket files lived only on the feature branch, in-flight tickets would be
invisible from `main` and the cockpit would report nothing. Therefore:

1. Creating a ticket commits the folder and `ticket.md` **directly to `main`**.
2. Work happens on `ticket/NNNN-slug`, in a git worktree.
3. Gate verdicts and `plan.md` land on the branch and merge with the pull request.
4. The cockpit reads `main` for the ticket list and `gh pr list` for in-flight state.

`main` requires a pull request, with the owner's admin bypass retained and used
**only** for the stage-① ticket commit. Branch protection that blocks the sole
developer produces fights with the tooling, not safety.

### 7.3 Worktrees

`cont` runs from its directory against a live SQLite database in WAL mode.
Switching branches under a running application risks a half-migrated schema
against a live `-wal` file. Work therefore happens in a worktree
(`../cont-wt/0043-date-filter/`), which receives a **copy** of the database for
testing and never the live file. The owner already uses worktrees
(`cont/.worktrees/shift-control/`); this standardises the path.

---

## 8. Lifecycle

### 8.1 Twelve stages

| # | Stage | What happens |
|---|---|---|
| ① | intake | Owner describes it in any words. Chief classifies. Ticket created on `main`, `gh issue` opened. |
| ② | triage | Constitution slices loaded. Explorer locates files. **Lane decided.** |
| ③ | design | Architect writes `plan.md`. **Owner checkpoint 1.** Full lane only. |
| ④ | build | Worktree + branch. Implementer writes code and commits. |
| ⑤ | gates | 2–3 of 6, in parallel. Findings → fixer, max 2 rounds. |
| ⑥ | verify | `pytest` runs, application boots, change is exercised. |
| ⑦ | review | Summary + verdicts + diff. **Owner checkpoint 2.** |
| ⑧ | pr | Pull request opened, cheap gates re-run in CI. |
| ⑨ | staging | Branch deployed to staging. **Owner checkpoint 3.** |
| ⑩ | merge | Owner merges. `main` stays deployable. |
| ⑪ | release | Tag + deploy to production. **Owner checkpoint 4.** |
| ⑫ | close | Ticket archived, issue closed, changelog entry written. |

Staging deploys from the **branch, before merge**, so owner approval means the
change was seen running, not merely read as a diff.

### 8.2 Lanes

| Lane | Stages | When |
|---|---|---|
| **fast** | ① ④ ⑤(cheap gates only) ⑦ ⑧ ⑩ | A string, a colour, a label. No plan, no staging, no LLM gates. |
| **full** | all twelve | New feature, schema change, anything touching money or auth. |

The chief selects the lane at ② and states it. The owner may override.

**Lane selection rules:** `fast` requires all of — no new file, no schema change,
no route added or removed, no dependency change, diff under 50 lines, no path
matching the security-sensitive list in the constitution. Any violation forces
`full`. When in doubt, `full`.

### 8.3 Git conventions

| Rule | Form |
|---|---|
| Branch | `ticket/NNNN-slug`, always. Created by the chief; the owner never types it. |
| Commit | `type(scope): summary` — types `feat` `fix` `refactor` `chore` `docs` `test` `perf`. English. |
| Scope | One ticket, one branch, one pull request. |
| `main` | Always deployable. |

This replaces the existing mixed convention in `cont`
(`feat/caja-module` alongside `feature/shift-control`).

**Note on `v2`:** `cont` has a long-lived `v2` branch. Long-lived branches drift
until merging them becomes its own project. Under Taller, `v2` would become a
series of tickets merged individually. This is recorded as an observation; it is
out of scope for this specification.

---

## 9. Gates

### 9.1 Roster

| Gate | Catches | Implementation |
|---|---|---|
| Constitution | Hardcoded colours/fonts, wrong layer, bad naming, `.md` in repository root, single-use scripts committed, override without a reason | **Python linter** + `cheap` model |
| Security | CSRF, missing `@permission_required`, SQL injection, secrets, transaction safety | `thinker` |
| Code quality | Reuse, dead code, error handling, simplification | `worker` |
| Size / complexity | File and function length against `thresholds`, duplication | **Python only** |
| UX / design | Bootstrap conventions, Spanish UI strings, mobile, accessibility, tokens respected | `worker` |
| Tests | Tests ran, passed, and exercise the change | **Python only** (`pytest`) |

Three of six require no model.

### 9.2 Selection

The chief selects gates by the paths a change touched, declared in the
constitution. A CSS change does not run the security gate; a migration does not
run UX. A typical ticket runs two or three. The security gate is **mandatory**
for any path on the constitution's security-sensitive list, regardless of lane.

### 9.3 Severity policy

| Severity | Action |
|---|---|
| `BLOCKER`, `HIGH` | Auto-fix, **maximum 2 rounds**, then stop and escalate |
| `MEDIUM` | Reported in the owner's summary. Never auto-fixed. |
| `LOW`, `NIT` | Logged in the ticket. No action unless the owner asks. |

The 2-round cap is the cost control: without it, 12 findings spawn 12 fixes which
re-trigger the gates, recursively.

### 9.4 CI is a backstop, not a second opinion

`.github/workflows/taller-ci.yml` runs **only** the three model-free gates —
constitution linter, size, `pytest`. No API key, no per-push LLM cost, under a
minute. It replaces the existing `code-review.yml`, `security.yml` and
`design-review.yml` workflows.

### 9.5 Amendment, not argument

A gate the owner can talk out of is not a gate. When a rule is wrong, the rule
changes via `/taller:amend`, which commits the amendment. Gates do not accept
justifications at review time. This is the mechanism intended to prevent the
decay visible in `REFACTORING_PLAN.md` → `REFACTORING_PLAN_ORIGINAL.md` →
`CONSOLIDATED_REFACTORING_PLAN.md`.

---

## 10. Components and build order

### 10.1 Plugin layout

```
programas/taller/
├── .claude-plugin/plugin.json
├── hooks/session-start.py         injects chief + 00-index.md
├── skills/
│   ├── chief/                     classify → lane → slices → dispatch
│   ├── onboarding/                derive facts, interview intent, write constitution
│   └── ticket/                    create · resume · close
├── agents/
│   ├── explorer.md      architect.md      implementer.md      fixer.md
│   ├── gate-constitution.md  gate-security.md  gate-quality.md  gate-ux.md
│   └── summariser.md
├── commands/
│   ├── taller-new.md              /taller:new "<description>"
│   ├── taller-status.md           all tickets, all projects
│   ├── taller-approve.md          owner checkpoint
│   ├── taller-resume.md           resume after a dead session
│   ├── taller-amend.md            change a constitution rule
│   ├── taller-onboard.md          new · adopt
│   ├── taller-brand.md            brand new · brand edit
│   ├── taller-models.md           probe
│   ├── taller-stage.md            deploy a branch to staging
│   └── taller-doctor.md           health check
├── lib/
│   ├── gates/constitution.py      size.py      tests.py
│   ├── tickets.py                 read/write ticket folders
│   ├── constitution.py            resolve hub + project + overrides
│   ├── models.py                  alias resolution, probe, fallback
│   └── registry.py                ~/.taller/projects.json
├── cockpit/                       Flask application
└── templates/                     constitution scaffolds, CI workflow, PR template
```

### 10.2 Unit boundaries

| Unit | Does | Interface | Depends on |
|---|---|---|---|
| `registry.py` | Read/write the project registry | `list_projects()`, `add_project()`, `get_project(path)` | filesystem |
| `constitution.py` | Resolve hub + profile + project + overrides into one rule set | `resolve(project_path) -> RuleSet` | `registry`, filesystem |
| `tickets.py` | Create, read, update, list tickets | `create()`, `load(id)`, `save(ticket)`, `list(project)` | filesystem, `gh` |
| `models.py` | Resolve aliases, probe availability, apply fallback | `resolve(role) -> model_id`, `probe()` | `taller.yml` |
| `gates/*.py` | Each returns findings for one dimension | `run(diff, ruleset) -> [Finding]` | `constitution` |
| `chief` skill | Classify, choose lane, select gates, dispatch | prompt contract, reads `RuleSet` | all of the above |
| `cockpit` | Render and write ticket state | HTTP, reads/writes the same files | `tickets`, `registry`, `constitution` |

Every unit is testable without the others. `gates/*.py` take a diff and a rule
set and return findings — no filesystem or network assumptions.

### 10.3 Build order

| Phase | Contents | Effort | Delivers |
|---|---|---|---|
| **A** | Hub, constitution, onboarding (`new` + `adopt`), brands | ~3 sessions | G1, G3. `cont` preamble ≤ 800 tokens; Front office duplication collapsed |
| **D** | Tickets | ~1 session | G5. Work survives session death |
| **B** | Chief, routing, model roster, `models probe` | ~2 sessions | G2, G6 |
| **C** | Gates — constitution linter first, LLM gates after | ~2–3 sessions | G4 |
| **F** | GitHub wiring, staging environment | ~1 session | Staging exists; one CI workflow replaces three |
| **E** | Cockpit | ~2–3 sessions | G7 visible; board, spend chart, health |

Each phase is independently useful. A and D alone address problems 1.1 and 1.3.
**Each phase gets its own implementation plan**, written when the previous phase
is complete.

---

## 11. Onboarding

### 11.1 Two entry points, one wizard

`taller new <name>` and `taller adopt` run the same question list. `adopt`
arrives with more answers pre-filled.

| Step | Question | Source |
|---|---|---|
| ① | What is this, in your words? | Owner |
| ② | Profile? `[flask-hotel]` · static-tool · python-app · custom | Owner, inferred default |
| ③ | Brand? `[purobeach]` · new brand… · none | Owner, inferred default |
| ④ | What must never break? | **Owner only** — no scan can answer this |
| ⑤ | Confirm derived facts | Machine proposes, owner corrects |
| ⑥ | Summary of everything to be created | **Owner approval** |

Nothing is written before step ⑥.

### 11.2 Derive facts, interview intent

The machine extracts what is observable: stack, dependencies, directory
structure, existing CSS custom properties, route patterns, naming conventions,
test layout, git history. It asks the owner only what is not in the code:
purpose, users, what must never break, brand intent, priorities.

For `cont` this is 6–8 questions rather than 40, and the answers are the ones no
repository scan could produce.

### 11.3 Properties

- One question at a time, with a recommended default in brackets.
- Inferred facts are shown for correction rather than requested as input.
- **Resumable** — answers are written to a scratch file as they are given, so a
  dead session does not restart the interview.
- `adopt` diffs the derived local constitution against the hub and **deletes what
  is already shared**, so adoption reduces text rather than adding it.

---

## 12. Cockpit

Flask 3.0 + Jinja2 + Bootstrap 5, bound to `127.0.0.1`. **No database.** It reads
`~/.taller/projects.json`, scans each project's `.taller/work/*/status.yml`, and
calls `gh` for pull request state.

| Screen | Contents |
|---|---|
| Board | Every ticket, every project, in columns by stage ① → ⑫. Owner checkpoints highlighted when waiting. |
| Ticket | The ask, the plan, every gate verdict, the diff, and approve / reject / change. |
| Spend | Tokens by ticket, week, model tier, and gate. |
| Constitution | Read and edit rules; saving commits the amendment. |
| Health | Per project: stray root files, hardcoded hex count, largest files, coverage. |

The cockpit **writes the same files the terminal writes**. Approving in the
browser and approving in the terminal are the same operation on the same
`status.yml`. It is a view and a writer, not a second system.

The onboarding wizard (section 11) runs in the cockpit as a web form using the
identical question list.

---

## 13. GitHub and staging

| Piece | Specification |
|---|---|
| `.github/workflows/taller-ci.yml` | Model-free gates only. Replaces `code-review.yml`, `security.yml`, `design-review.yml`. |
| Pull request template | Generated from `ticket.md` and gate verdicts. |
| Branch protection | Ruleset: require a pull request, require `taller-ci` green. Admin bypass retained for stage ① only. |
| Issue ↔ ticket | Issue opened at ①, referenced by the pull request, closed at ⑫. |

### 13.1 Staging

```bash
docker compose -p <project>-staging \
  -f docker-compose.yml -f docker-compose.staging.yml up -d
```

Separate project name, separate port, `./data-staging/` holding a **copy** of
production data. Same Caddy, same Basic Auth, reachable over Tailscale.
Production is unreachable from anything on the branch.

**Constraint:** GitHub Actions cannot reach a Tailscale-only private server.
There is no route from a hosted runner. Therefore staging deployment is
`taller stage <id>` — a **local command the owner runs**, not CI. A self-hosted
runner on the server would automate this and is explicitly deferred: it adds
infrastructure to patch and maintain for the sake of not typing one command.

### 13.2 Remotes

The `taller` plugin repository and the `~/.taller` hub repository are created
**local-only**. No GitHub remote is created without the owner's explicit
instruction. Nothing in this design requires a remote; the hub benefits from one
for multi-machine sync, which is the owner's decision to make.

---

## 14. Failure behaviour

| Failure | Behaviour |
|---|---|
| `BLOCKER` survives 2 fix rounds | Stop. `stage: blocked`. Escalate with what was attempted and why it failed. Never proceeds quietly. |
| Model unavailable or overloaded | Fall back per `fallback:`; record the substitution in `status.yml`. No mid-ticket crash. |
| Session dies or context is compacted | Nothing lost. State is on disk. `/taller:resume <id>`. |
| Subagent returns empty or malformed output | One retry, then escalate. No loops. |
| Two tickets touch the same files | Chief warns at ① and offers to combine. Worktrees keep them physically separate regardless. |
| Tests fail at ⑥ | Return to ④, maximum 2 rounds, then `blocked`. |
| Staging deployment fails | Ticket remains at ⑧. Production is not involved. |
| Owner rejects at ⑦ | Worktree and branch deleted. Ticket returns to ②. The owner's reason is recorded in `notes.md` so the retry does not repeat the mistake. |
| Budget `per_ticket_stop` exceeded | Stop and ask the owner before continuing. |
| A gate flags a rule the owner disagrees with | `/taller:amend`. The rule changes; the gate is not overridden. |
| `gh` unauthenticated | Stages ①(mirror), ⑧, ⑫ fail with a clear message. Local stages continue. |
| Hub rules changed mid-ticket | Verdicts record `hub_sha`. A mismatch at ⑦ warns the owner that rules moved under the ticket. |

---

## 15. Testing

### 15.1 Python is tested as Python

`gates/constitution.py`, `gates/size.py`, `gates/tests.py`, `tickets.py`,
`constitution.py`, `models.py`, `registry.py` — `pytest`, fast, deterministic.
These are the load-bearing components, and they are deliberately the ones that
are not prompts.

### 15.2 A fixture repository of deliberate violations

`tests/fixtures/broken-app/` — a small, intentionally non-compliant Flask
application containing known violations:

- 3 hardcoded hex values where a token exists
- a route missing `@permission_required`
- a function over the `max_function_lines` threshold
- an English string in the UI
- a `.md` file in the repository root
- an override with no stated reason

Each gate runs against it and each violation must be caught. This is a
**regression suite for prompts**: editing `gate-security.md` such that it stops
catching the missing decorator turns a test red. Without this, prompt quality
drifts silently.

### 15.3 Golden tickets

Twelve recorded real requests with their expected classification, lane, and gate
selection — asserting the chief routes correctly. Cheap, because routing runs on
`cheap`/`worker`.

### 15.4 `/taller:doctor`

Checks: constitution resolves without conflict, every gate executes, every
configured model is reachable, CI is green, the registry is valid, every
registered path exists.

### 15.5 Acknowledged limitation

The LLM gates are non-deterministic. Fixture tests reduce the risk; they do not
eliminate it. A gate will occasionally miss a real problem. This is why owner
checkpoint ⑦ exists and why `main` requires green CI — defence in depth rather
than one perfect filter.

---

## 16. Acceptance criteria

| # | Criterion | Baseline (2026-09-26) | Target |
|---|---|---|---|
| 1 | `cont` always-loaded preamble | ~7,000 tokens | ≤ 800 tokens |
| 2 | Hardcoded hex in `cont/templates/` | 26 | 0 |
| 3 | Front office + Front-office-modules local constitutions | 9,466 chars each, identical | < 2,000 chars each |
| 4 | CI workflows per repository | 3 | 1 |
| 5 | Review directories duplicated across projects | 6 projects | 0 |
| 6 | Non-README `.md` files in `PuroBeachClub` root | 40+ | ticketed, trending down |
| 7 | Ticket resumable after a killed session | not possible | every ticket |
| 8 | Tickets with a recorded spend figure | 0 | every ticket |
| 9 | Staging environment | none | one per Flask project |
| 10 | Owner approval checkpoints before production | informal | 4, enforced |

Criteria 1–5 are met by phases A–C. Criterion 6 is a consequence, not a
deliverable of this build.

---

## 17. Decisions and rejected alternatives

| Decision | Rejected | Reason |
|---|---|---|
| Superpowers as the engine, Taller as the addition | Adopt Spec Kit wholesale; build everything from scratch | Spec Kit is agent-agnostic, so it cannot use Claude Code subagents — the team structure would be lost. It also adds a second toolchain (Python CLI + `uv`) and is verbose by design, which conflicts with the cost goal. Building from scratch means re-implementing working brainstorm/plan skills. |
| Tickets as files in the repository, GitHub Issues as a mirror | Issues as the store; local SQLite | Agents are the heaviest readers. Files cost no API ceremony and no network. SQLite is a second source of truth that never appears in a pull request diff. |
| Ticket creation commits to `main` | Tickets live only on the branch | Otherwise in-flight tickets are invisible from `main` and the cockpit reports nothing. |
| Security gate on `thinker` | `worker` | Owner's explicit decision. A missed authorisation check is liability. |
| Fable 5.1 unassigned | Assign it to the UX gate | No evidence it outperforms `worker` there. |
| Two-layer model indirection | Model names in agent files | Model availability cannot be enumerated and changes without notice. One line to change, not thirteen. |
| Staging as a local command | Self-hosted GitHub runner | No route from a hosted runner to a Tailscale-only server. A runner is infrastructure to maintain in exchange for not typing one command. |
| Constitution amended, never argued with | Gates accept justifications | A gate that can be talked out of is not a gate. |
| Derive facts, interview intent | Full interview; full auto-derivation | Interview alone re-types what the repository already states. Derivation alone can only describe what the code *is*, never what was *meant*. |
| Profiles + modules, capped by a two-project rule | One shared constitution; per-project only | The owner has three genuinely different project shapes. Unbounded modules become their own maintenance project. |
| Commit messages in English | Spanish | Consistent with the existing code/comment convention. |
| Local-only repositories initially | Create GitHub remotes now | Publishing is the owner's decision, not a design requirement. |

---

## 18. Out of scope

- Refactoring `PuroBeachClub` (Taller will generate tickets for it; it does not
  perform the work as part of its own construction)
- Merging or retiring the `cont` `v2` branch
- Multi-user access, authentication, or a hosted cockpit
- Self-hosted CI runners
- Repairing the failing GitHub MCP server (Taller uses `gh`)
- Any fourth profile or module not required by two existing projects
