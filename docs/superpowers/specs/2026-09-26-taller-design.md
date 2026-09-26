# Taller — Design Specification

**Date:** 2026-09-26
**Status:** Approved by owner (design phase complete) · revised after spec review, iteration 3
**Owner:** Catia Schubert
**Pilot project:** `C:\Users\catia\cont` (payment-reconciliation)

---

## 0. Document scope and how to read it

This is the **system architecture specification** for Taller: a development
environment that wraps Claude Code so that one orchestrating agent holds project
context and delegates work to specialist agents, through quality gates, under
owner approval, with GitHub as the system of record.

The system has six phases (A–F, §10.4). All six are specified here because they
share seven contracts:

| Contract | Section |
|---|---|
| Slice vocabulary (nine, closed) | §4.3 |
| `RuleSet` and the two resolution chains | §4.4 |
| `overrides.md` format and suppression mechanism | §4.5 |
| The resolved snapshot (`.taller/resolved.json`) | §4.6 |
| Ticket format and `status.yml` | §7 |
| `Finding`, rule-id severities, and the verdict file | §7.4, §9.7 |
| Spend, weights and budget | §7.5 |

The cockpit cannot be designed without the ticket format; the gates cannot be
designed without knowing how the constitution resolves. Splitting the
specification would have produced seven documents that contradict each other.

**Implementation is not planned here.** Each phase gets its own implementation
plan, written separately, in the order given in §10.4. The first plan to be
written covers **Phase A only**.

**Language:** this document, all code, identifiers, comments, and commit messages
are in English. Application UI strings are in Spanish. This follows the owner's
existing convention and is configuration, not a constant (§5.1).

---

## 1. Problem statement

The owner runs several production Flask applications for a hotel business and
builds them with Claude Code. Five concrete problems, measured on 2026-09-26.

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

| # | Goal | Measured by | Phase |
|---|---|---|---|
| G1 | Cut always-loaded context | `cont` preamble ≤ 800 tokens (from ~7,000) | A |
| G2 | One orchestrator the owner talks to | Owner states intent once per ticket | B |
| G3 | Shared rules, declared once | Front office + Front-office-modules authored local content each < 2,000 chars | A |
| G4 | Enforced conventions | No new unsuppressed hardcoded colour or font value reaches `main` | C |
| G5 | Work survives session death | Any ticket resumable from disk after a killed session | D |
| G6 | Visible cost | Every ticket records weighted token spend by model | B |
| G7 | Owner keeps final control | Checkpoints 2 (review) and 4 (release) unconditional; 1 (design) and 3 (staging) lane-dependent. Nothing reaches production unapproved. | B |
| G8 | Uniform across projects | Identical `.taller/` shape, stages, ticket format and commands regardless of stack or brand | A |

### Non-goals

- **Not a replacement for superpowers.** Superpowers remains the brainstorm →
  plan → execute → verify engine. Taller adds what it lacks.
- **Not a persistent daemon.** See §3.1.
- **Not multi-user.** Single operator. No auth in the cockpit; it binds to
  `127.0.0.1`.
- **Not a Spec Kit installation.** Ideas adopted (§17), toolchain not.
- **Not a refactor of existing applications.** Taller *generates tickets* to
  clean up `PuroBeachClub` and the 26 existing hex values in `cont`; it does not
  perform that cleanup as part of its own construction.
- **Not a billing system.** Spend is measured in weighted tokens. A currency
  figure is produced only if the owner supplies a pricing table (§7.5).

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

**Load by need.** `00-index.md` is a routing map naming **slices** (§4.3), not
files. Its default table, which `taller project adopt` generates and the chief
parses:

| Work touches | Slices loaded |
|---|---|
| *always, at stage ②* | `stack`, `never`, `overrides` |
| Template or CSS | `ux`, `brand` (+ the brand's `tokens.css`) |
| Route or query | `architecture`, `security` |
| New feature | `product`, `architecture`, `conventions` |
| Any path in `paths.security_sensitive` | `security` |

`never` and `overrides` are always loaded: both are a few lines, and a
prohibition or a suppression the chief cannot see has no effect at read time.
Discovering a hard prohibition at ⑤ rather than ② wastes a whole build. All nine
slices of §4.3 appear in this table.

`00-index.md` format: YAML front matter holding the routing table above, then
prose of at most 40 lines summarising each slice in one sentence. It is
**generated**, never hand-written, and excluded from the G3 measurement (§16).

### 3.2 Three artifacts, plus runtime state

```
programas/taller/          ① THE PLUGIN — the machinery.
                              Generic; no hotel- or brand-specific knowledge.

~/.taller/                 ② THE HUB — rules, brands, registry. A git repository.
                              Contains ONLY versioned content.

~/.taller-run/             ③ RUNTIME STATE — locks, worktrees, wizard scratch.
                              NOT a git repository, never versioned.

<project>/.taller/         ④ PER PROJECT — what differs from the hub, plus tickets.
```

Runtime state is deliberately outside the hub repository. A git worktree of
another repository nested inside the hub's working tree would let an amendment
commit sweep a whole project checkout into the hub, and a hub revert could
destroy the worktree Taller commits through.

### 3.3 Layer responsibilities

| Layer | Provided by |
|---|---|
| Brainstorm → plan → execute → verify | superpowers (soft dependency, §3.4) |
| Constitution, chief, routing, gates, tickets, cockpit | Taller |
| Issues, pull requests, CI, branch protection | GitHub via `gh` CLI |

The GitHub MCP server currently fails authentication (HTTP 401, stale token).
Taller uses the `gh` CLI, which is authenticated as `menfistoo` and working. The
design has no dependency on the GitHub MCP server.

### 3.4 Dependencies

| Dependency | Kind | Behaviour if absent |
|---|---|---|
| Claude Code | hard | Taller is a Claude Code plugin |
| Python 3.11+ | hard | The library, CLI, gate scripts, spend accounting and cockpit are Python |
| `gh` CLI, authenticated | hard for D/F | Issue mirroring and PR stages fail with a clear error; local stages still work |
| superpowers | **soft** | Taller falls back to its own minimal plan step |
| Docker Compose | hard for staging only | Stage ⑨ is skipped with a clear message |

Superpowers is a soft dependency so the plugin remains standalone and
transferable.

### 3.5 Command surface

**`src/taller/` is the single implementation.** The CLI and the slash commands
are both thin front ends that import it. Neither contains behaviour the other
lacks; each exposes the subset that makes sense for its context.

| Surface | Commands | Why |
|---|---|---|
| **`taller` CLI** (Python console script) | `project new`, `project adopt`, `brand new`, `brand edit`, `ticket new\|show\|list\|transition\|approve\|reject\|resume\|close`, `models probe`, `resolve`, `scan`, `stage`, `doctor`, `cockpit` | Runs outside a session — a terminal, a script, CI, or the deployment host. |
| **Slash commands** (in-session) | `/taller:new`, `/taller:approve`, `/taller:reject`, `/taller:resume`, `/taller:amend`, `/taller:status`, `/taller:onboard` | Need the conversation: they dispatch agents and interpret the owner's intent. |

**Naming is disjoint.** Project lifecycle is always `taller project …`; ticket
lifecycle is `taller ticket …` on the CLI and `/taller:new` in a session.
`/taller:new` creates a **ticket**; `taller project new` creates a **project**.
No verb means two things. `/taller:reject` exists because a rejection is a
conversational act whose reason must reach `notes.md`.

---

## 4. The hub

```
~/.taller/                         git repository — versioned content ONLY
├── taller.yml                     DEFAULT config: models, effort, budget,
│                                  thresholds, language, weights, paths floor
├── projects.json                  registry: path, profile, brand, last seen
├── brands/
│   ├── purobeach/
│   │   ├── tokens.css             THE source of truth for colour + font VALUES
│   │   ├── brand.md               which token to use when (names, never values)
│   │   └── assets/                logo, favicon, fonts, images
│   └── <slug>/                    same shape, always
├── modules/                       each file declares the slice it provides
│   ├── stack/flask-sqlite.md          → stack
│   ├── stack/static-js.md             → stack
│   ├── stack/python-app.md            → stack
│   ├── security/web-app.md            → security
│   ├── security/minimal.md            → security
│   ├── conventions/python.md          → conventions
│   ├── conventions/js.md              → conventions
│   ├── ux/bootstrap-es.md             → ux
│   └── never.md                       → never
├── profiles/
│   ├── flask-hotel.yml    static-tool.yml    python-app.yml
└── templates/new-project/         stack skeletons

~/.taller-run/                     NOT versioned
├── .lock                          hub write lock (§10.3)
├── onboarding/<name>.yml          wizard scratch (§11.3)
└── worktrees/<project>-main/      long-lived `main` worktree (§7.3)
```

### 4.1 Profiles

A profile names the modules a project inherits, its default brand, and config
that is stack-specific rather than global.

```yaml
# ~/.taller/profiles/flask-hotel.yml
name: flask-hotel
description: Flask + SQLite WAL + Jinja2 + Bootstrap 5 + Docker + Caddy
modules:
  - stack/flask-sqlite
  - security/web-app
  - conventions/python
  - conventions/js
  - ux/bootstrap-es
  - never
brand: purobeach
language: {code: en, ui: es, commits: en}
paths:
  security_sensitive:          # APPENDS to the hub floor (§4.4)
    - "routes/**"
    - "blueprints/**"
    - "database.py"
    - "**/auth*.py"
    - "**/permissions*.py"
    - "migrate_*.py"
    - "wsgi.py"
    - "docker-compose*.yml"
    - "Caddyfile"
  ui:
    - "templates/**"
    - "static/**/*.css"
    - "static/**/*.js"
  layers:
    "routes/**":     ["database", "utils.*"]
    "blueprints/**": ["database", "utils.*"]
    "database.py":   []
  tests_dir: "tests"
smoke:                         # §9.6
  kind:      http
  boot:      "python run_local.py"
  ready:     "http://127.0.0.1:5000/"
  timeout_s: 30
  routes:    ["/"]             # always exercised, plus the mapped routes
```

```yaml
# ~/.taller/profiles/python-app.yml
name: python-app
description: Packaged Python desktop application (PyInstaller)
modules: [stack/python-app, security/minimal, conventions/python, never]
brand: none
language: {code: en, ui: none, commits: en}   # wisper has no UI
paths:
  security_sensitive: ["build.py", "*.spec"]
  ui: []
  layers: {}
  tests_dir: "tests"
smoke:
  kind:      import            # import the entry module; assert no exception
  module:    "main"
  timeout_s: 20
```

`language.ui: none` disables every UI-language rule, so `wisper` is never checked
for Spanish strings.

The three initial profiles map to the owner's three existing project shapes:

| Profile | Existing projects |
|---|---|
| `flask-hotel` | cont, PuroBeachClub, HK, SSTT, Front office, Front-office-modules |
| `static-tool` | Creador de precios (static HTML/JS + Python helper, own `logo.png`) |
| `python-app` | wisper (PyInstaller desktop app, no UI) |

**YAGNI constraint:** no module is created until **two** projects need it. No
fourth profile until a real project requires one.

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
renders a **swatch page** (a standalone HTML file opened locally), so a brand is
reviewed visually rather than as a list of hex codes.

### 4.3 Slice vocabulary

Exactly nine slices. The list is closed; adding one changes this specification.

| Slice | Content | Provided by |
|---|---|---|
| `product` | What this does, who uses it, what must never break | **project only** |
| `architecture` | This project's layers and dependency rules | **project only** |
| `stack` | Runtime, framework, database, deployment shape | hub module |
| `conventions` | Naming, DB patterns, routes, code style | hub module(s) |
| `security` | Auth, CSRF, permissions, secrets, transaction safety | hub module |
| `ux` | Component conventions, mobile, accessibility, token usage, UI-string language | hub module |
| `brand` | Which token when — plus the brand's `tokens.css` | hub brand |
| `never` | Hard prohibitions | hub module; project may **append** |
| `overrides` | Project rule suppressions, each with a reason | **project only** |

### 4.4 Resolution: two chains, deliberately separate

**Chain 1 — configuration** (later wins, deep merge):

```
hub taller.yml  →  profile  →  project taller.yml
```

Covers `models`, `model_aliases`, `effort`, `fallback`, `budget`, `weights`,
`pricing`, `thresholds`, `language`, `paths`, `smoke`. **Nothing in
`constitution/` sets configuration.**

**List merge rule.** Lists **replace** by default, with one exception:
`paths.security_sensitive` is **append-only** at every level. The hub defines a
global floor; profiles and projects add to it; nothing can remove an entry. A
project able to narrow its own security surface would make §8.2's mandatory gate
optional.

**Chain 2 — slice text** (concatenated in order; nothing is ever removed):

```
hub modules (profile order)  →  project constitution/  →  project never.md append
```

Slice prose is **only ever appended**. A project cannot delete a hub
prohibition. The only way to neutralise a specific rule is `overrides.md` (§4.5),
which suppresses by rule id and records a reason.

```python
ResolvedSlice = {
    "name":    str,          # one of the nine
    "sources": [str],        # absolute paths, in application order
    "text":    str,          # concatenated content
}

RuleSet = {
    "project":    {"path": str, "profile": str, "name": str},
    "slices":     {slice_name: ResolvedSlice},   # absent key = slice not provided
    "brand":      {"slug": str, "tokens_path": str,
                   "tokens": {str: str}} | None, # None when brand == "none"
    "paths":      {"security_sensitive": [glob], "ui": [glob],
                   "layers": {glob: [str]}, "tests_dir": str},
    "smoke":      {str: object},                 # §9.6
    "thresholds": {str: int},
    "models":     {role: model_id},              # aliases already resolved
    "effort":     {role: str},
    "budget":     {str: int},
    "weights":    {str: float},                  # §7.5
    "pricing":    {model_id: {str: float}} | None,
    "language":   {"code": str, "ui": str, "commits": str},
    "overrides":  [Override],                    # §4.5
    "hub_sha":    str,
}
```

**Determinism:** `resolve()` performs no network access and no model calls. It is
pure over the filesystem, so it is directly unit-testable.

`~/.taller/` is a git repository because one edit can affect six projects.
Amendments have history and can be reverted. `hub_sha` is the hub's `HEAD` at
resolution time and is recorded on every gate verdict (§7.4).

### 4.5 `overrides.md` — format and mechanism

Every rule a gate can report has a **stable id** in one namespace, shared with
`Finding.rule` (§7.4): `<gate>.<rule>`. Ids and their default severities are
declared in §9.7 and are part of each gate's public surface.

```markdown
---
overrides:
  - rule:   size.file-too-long
    scope:  "blueprints/beachclub.py"     # glob, or "*" for project-wide
    reason: "6,235-line blueprint is being split ticket by ticket; see 0031."
    until:  2026-12-31                    # optional
---

Prose context for a human reader.
```

```python
Override = {"rule": str, "scope": glob, "reason": str | None, "until": date | None}
```

**Mechanism.** Gates emit findings normally. A `Finding` whose `rule` and `file`
match an active override is **downgraded to `NIT`** and annotated with the
reason — never silently dropped, so it stays visible in the verdict file, on the
cockpit, and in `taller scan`. Per §9.3 a `NIT` takes no action, which is the
intent: an override is a decision to ship a known deviation.

**Malformed or expired overrides** suppress nothing and are themselves reported:

| Condition | Rule id | Severity |
|---|---|---|
| No `reason` | `constitution.override-without-reason` | HIGH |
| Past `until` | `constitution.override-expired` | HIGH |
| Targets a non-suppressible rule | `constitution.override-not-permitted` | BLOCKER |

**Non-suppressible rules.** Every rule of the `never` slice and every rule of the
security gate. This is what makes `never` mean never, and it guarantees no
security `BLOCKER` can be downgraded to silence.

### 4.6 The resolved snapshot

CI cannot see the hub. The hub is a local-only git repository (§13.2), so a
hosted GitHub runner cannot resolve a `RuleSet`, cannot read the brand
`tokens.css`, cannot know `paths.layers` or `thresholds`, and cannot record
`hub_sha`. Without a fix, the constitution and size gates could not run in CI at
all — which would make §9.4, §13's required check, and §15.5's defence-in-depth
argument false.

**`resolve()` therefore writes a snapshot to `<project>/.taller/resolved.json`,
committed to the project repository.** It contains the full `RuleSet` with slice
text included, plus the brand's parsed tokens. CI's gates load the snapshot
instead of resolving.

| Property | Consequence |
|---|---|
| Committed and diffable | A pull request shows when the rules governing it changed |
| Self-contained | CI needs no hub, no remote, no secrets, no deploy key |
| Carries `hub_sha` | Verdicts from CI are as traceable as local ones |

**Staleness.** `resolve()` is run, and the snapshot refreshed, at `project
adopt`, at every `/taller:amend`, and at stage ② of every ticket. Locally — where
the hub exists — the constitution gate compares `resolved.json`'s `hub_sha`
against the hub's `HEAD` and reports `constitution.resolved-snapshot-stale`
(HIGH) on mismatch. In CI it cannot make that comparison and does not try; it
validates against the snapshot as committed. The local check is what keeps the
snapshot honest, and it runs before every pull request exists.

`taller resolve` refreshes it on demand.

---

## 5. Per-project layout

```
<project>/
├── CLAUDE.md                      stub: points at .taller/constitution/00-index.md
└── .taller/
    ├── taller.yml                 CONFIG OVERRIDES ONLY — omitted keys from the hub
    ├── resolved.json              generated snapshot, committed (§4.6)
    ├── constitution/
    │   ├── 00-index.md            generated routing map (§3.1)
    │   ├── product.md             slice: product
    │   ├── architecture.md        slice: architecture
    │   ├── never.md               slice: never — OPTIONAL, appends to the hub's
    │   └── overrides.md           slice: overrides (§4.5)
    └── work/
        └── NNNN-slug/             tickets
```

The project write lock lives at `~/.taller-run/locks/<project>.lock`, not in the
repository (§10.3). Only `product`, `architecture`, `never` (append) and
`overrides` are authored locally; the other five slices come from the hub. A
project with no deviations has a `taller.yml` of zero lines and an `overrides.md`
with an empty list — the target state for Front office and Front-office-modules.

### 5.1 taller.yml

```yaml
# ~/.taller/taller.yml — defaults for every project
model_aliases:                # the ONLY place a concrete model name appears
  thinker:  opus
  worker:   sonnet
  cheap:    haiku
  creative: fable             # untested; unassigned by decision

models:                       # role -> alias. Nine roles, matching §6.
  architect:     thinker
  implementer:   worker
  fixer:         worker
  gate_security: thinker
  gate_quality:  worker
  gate_ux:       worker
  explorer:      cheap
  scribe:        cheap
  summariser:    cheap

effort:
  architect:     high
  implementer:   medium       # named explicitly: code-writing must not be `low`
  fixer:         medium
  gate_security: medium
  gate_quality:  medium
  gate_ux:       medium
  default:       low          # explorer, scribe, summariser

fallback: worker              # unreachable model degrades, never crashes

language: {code: en, ui: es, commits: en}

paths:
  security_sensitive:         # GLOBAL FLOOR — profiles and projects append (§4.4)
    - ".env*"
    - "**/*secret*"
    - "**/*credential*"

weights:                      # relative cost weights, tunable (§7.5)
  input:        1.0
  cache_write:  1.25
  cache_read:   0.1
  output:       5.0

pricing: null                 # optional; owner-supplied, per million tokens (§7.5)

budget:                       # compared against spend.weighted_tokens (§7.5)
  per_ticket_warn: 120000
  per_ticket_stop: 320000

thresholds:
  max_file_lines:       800
  max_function_lines:    80
  max_fast_lane_lines:   50
  max_fix_rounds:         2
  min_coverage_pct:       0   # 0 = report only, never fail
  dup_block_lines:       12
```

```yaml
# <project>/.taller/taller.yml — e.g. cont, stricter about file size
thresholds:
  max_file_lines: 400
paths:
  security_sensitive:          # APPEND-ONLY (§4.4)
    - "reconciliation/**"
```

A new model release is **one line in `model_aliases`**, not one edit per agent
file. `fallback` means a model name the account cannot reach degrades to `worker`
rather than failing mid-ticket.

**There is no `chief` key, deliberately.** The chief is the owner's own session,
and Taller cannot set the model of the session it runs inside. See §6.1.

---

## 6. Model roster

Nine agent roles, matching `models:` in §5.1 and `agents/` in §10.1 exactly.
Four gates have no agent at all.

| Role | Alias | Rationale |
|---|---|---|
| Scribe | `cheap` | Transcribes the owner's words into `ticket.md` |
| Explorer | `cheap` | Locates files, reports paths. High volume, low judgement. |
| Architect | `thinker` | The one place to spend. A bad plan costs more than the model. |
| Implementer | `worker` | Writes code |
| Fixer | `worker` | Applies findings already reasoned about by a gate |
| Security gate | `thinker` | A missed `@permission_required` is liability. Owner's explicit decision. |
| Code quality gate | `worker` | Runs often; sufficient |
| UX gate | `worker` | Checks conventions, does not invent them |
| Summariser | `cheap` | Condenses verdicts for the approval view |

Constitution, size, tests and smoke gates are Python and take no model (§9.1).

### 6.1 The chief's model

The chief runs in the owner's session, so its model is whatever the owner
selected. Taller cannot change it. `/taller:new` reads the session model from the
transcript (§7.5) and warns when it is mismatched:

| Situation | Warning |
|---|---|
| Session on `thinker`, ticket triaged `fast` | "This ticket is a fast-lane fix; your session is on Opus. Consider Sonnet." |
| Session on `cheap`, ticket triaged `full` with a design stage | "This ticket needs a plan; your session is on Haiku. Consider Opus." |

A warning only. It never switches models and never blocks.

### 6.2 Model availability

The set of available models cannot be enumerated from the CLI (`--model` accepts
an alias or a full name and does not list options). `taller models probe` sends a
one-token request to each candidate (`opus`, `sonnet`, `haiku`, `fable`, plus any
name the owner adds) and reports which are reachable, with latency. This replaces
guessing and is re-run whenever a new model ships.

**Fable 5.1** is deliberately unassigned. It is available as `fable` and is a
plausible candidate for the UX gate, but there is no evidence it outperforms
`worker` there. Assigning it on speculation would cost a debugging cycle.

---

## 7. The ticket

### 7.1 On disk

```
.taller/work/0043-danger-color/
├── ticket.md          the owner's words, verbatim, plus the classification
├── status.yml         machine state
├── notes.md           decisions and WHY, including rejection reasons
├── plan.md            full lane only
└── gates/             one verdict file per gate that ran, including smoke
```

```yaml
# status.yml
id: 43
slug: danger-color
title: El aviso de descuadre usa un rojo distinto al del resto
kind: bug                  # bug | feature | refactor | question | idea
lane: fast                 # fast | full
stage: review
branch: ticket/0043-danger-color
issue: 87
created: 2026-09-26T10:14:00
gates: [constitution, size, tests, smoke]   # EVERY gate that ran, ⑤ and ⑥
verdicts:
  constitution: {result: pass, blocker: 0, high: 0, medium: 0, low: 0, nit: 0, hub_sha: a3f9c21}
  size:         {result: pass, blocker: 0, high: 0, medium: 0, low: 0, nit: 0, hub_sha: a3f9c21}
  tests:        {result: pass, blocker: 0, high: 0, medium: 0, low: 2, nit: 0, hub_sha: a3f9c21}
  smoke:        {result: pass, blocker: 0, high: 0, medium: 0, low: 0, nit: 0, hub_sha: a3f9c21}
fix_rounds: 1
sync: ok                   # ok | pending  — remote mirror state (§7.3)
checkpoints:               # pending | approved | rejected | skipped
  design:  skipped         # not in the fast lane
  review:  pending
  staging: skipped         # not in the fast lane
  release: pending
spend:
  partial: false
  by_model:
    claude-haiku-4-5-20251001: {input: 1200, cache_write: 9000, cache_read: 31000, output: 3100}
    claude-sonnet-5:           {input: 2400, cache_write: 22000, cache_read: 64000, output: 12600}
  total_tokens:    145300   # raw sum, for reference
  weighted_tokens:  98065   # §7.5 — this is what budget compares against
  cost: null                # populated only when `pricing` is configured
```

A genuine fast-lane example: replacing a hardcoded `#dc3545` with
`var(--app-danger)` in one template. It reached ⑦, so smoke has run and has a
verdict. A `full` ticket's `gates` would additionally contain `security`,
`quality` and/or `ux`.

### 7.2 What lives where

| File | Branch | Written at | Reason |
|---|---|---|---|
| `ticket.md` | **`main`** | ① | The ticket must be visible from `main` or the cockpit reports nothing |
| `status.yml` | **`main`** | ① and every stage transition | Same; also the resume key |
| `notes.md` | **`main`** | ① onward | §14 relies on it surviving branch deletion |
| `plan.md` | branch | ③ | Belongs to the work; merges with the PR |
| `gates/*.md` | branch | ⑤, ⑥ | Belongs to the work; merges with the PR |

**On rejection at ⑦** the gate verdict files and the owner's reason are copied to
`main` under `work/NNNN-slug/rejected/<timestamp>/` **before** the worktree and
branch are deleted.

### 7.3 Writing to `main` while the work is on a branch

Roughly a dozen times per ticket, making it the most frequent write in the
system. Taller maintains a **long-lived worktree of `main`** at
`~/.taller-run/worktrees/<project>-main/`, created at `taller project adopt`.
It is outside the project tree and outside the hub repository, so it never
interferes with the owner's running application, the ticket worktree, or `cont`'s
live SQLite WAL files.

`tickets.commit_to_main(project, files, message)`:

1. Take the project lock (§10.3).
2. `git -C <wt> fetch && git -C <wt> merge --ff-only origin/main`.
3. Write the files atomically; commit.
4. `git -C <wt> push`.

**Local state is the truth; the remote is a mirror.** Every failure degrades to
`sync: pending` rather than losing a transition:

| Failure | Behaviour |
|---|---|
| Fast-forward merge refused (owner committed on `main`, or the remote moved) | **Rebase** the ticket-file commits onto `origin/main` and retry once. Safe because these commits only ever touch `.taller/work/**/{ticket.md,status.yml,notes.md}`, so they cannot conflict with application code. |
| Rebase also fails, or the push is rejected | Commit stays local. `sync: pending` written to `status.yml`. The cockpit shows the ticket as unsynced with the reason. Work continues. |
| `sync: pending` present at the next `commit_to_main` | Retry the push first. `taller doctor` reports any ticket left `pending`. |

Commit-and-push is not atomic, and §10.3's atomic replace covers files only —
hence `sync` as an explicit, visible state rather than an assumed invariant.

`main` requires a pull request, with the owner's admin bypass retained and used
**only** by this function, for the three `main`-side files.

### 7.4 `Finding` and verdict format

```python
Finding = {
    "gate":      str,     # constitution | size | tests | smoke | security | quality | ux
    "severity":  str,     # BLOCKER | HIGH | MEDIUM | LOW | NIT
    "rule":      str,     # stable id, §9.7
    "file":      str,     # repo-relative; "" when not file-scoped (e.g. smoke boot)
    "line":      int,     # 1-indexed; 0 when file-level
    "message":   str,     # one sentence
    "fix_hint":  str | None,
    "overridden": {"reason": str, "source": str} | None,   # §4.5 downgrade
}
```

`gates/<name>.md` is YAML front matter plus a Markdown body:

```markdown
---
gate: tests
result: pass            # pass | fail | error
hub_sha: a3f9c21
ran_at: 2026-09-26T10:31:00
counts: {blocker: 0, high: 0, medium: 0, low: 2, nit: 0}
metrics:                # gate-specific, structured, optional
  tests_run: 184
  tests_passed: 184
  coverage_pct: 61.4
  duration_s: 22.8
findings: []
---

Prose explanation for the owner, written by the summariser.
```

`metrics:` is what the cockpit Health screen reads (§12); `counts` and `result`
are mirrored into `status.yml`. `result: error` means the gate could not run; it
is treated as `BLOCKER` for flow purposes and never as a pass.

### 7.5 Spend, weights and budget

Claude Code writes a session transcript at
`~/.claude/projects/<slug>/<session>.jsonl`. Each assistant record carries
`message.model` and a full `message.usage` (`input_tokens`,
`cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`), plus
`timestamp`, `gitBranch`, `agentName` and `isSidechain`. Verified against a live
transcript, not assumed.

`src/taller/spend.py` attributes usage to a ticket by:

1. **`gitBranch`** where present — every ticket owns a branch, so this is exact.
2. **Stage-transition time window** otherwise, for records written before the
   branch exists (stages ① and ②).

**Why a raw token sum is the wrong number.** Cache reads bill far below input
tokens, and output far above. In §7.1's example 95,000 of 145,300 tokens — 65% —
are cache reads. A budget compared against the raw sum would fire mainly on how
much context was re-read, not on cost, and G6 is "visible cost".

```
weighted_tokens = Σ over models Σ over fields ( tokens[field] × weights[field] )
```

`weights` (§5.1) are dimensionless and tunable; the shipped defaults reflect the
usual shape of Anthropic pricing (cache reads ≈ 0.1× input, output ≈ 5× input)
and are the owner's to adjust. **`budget` compares against `weighted_tokens`.**

`pricing` is optional and owner-supplied — per model id, per field, per million
tokens. When set, `spend.cost` is computed and the cockpit shows currency. When
unset it stays `null` and `taller doctor` notes that cost is unavailable. No
prices are shipped, because a stale price table is worse than an honest token
count.

`by_model` keys are concrete model ids as reported, not aliases, so the record
stays truthful when an alias is remapped or `fallback` fires. If any record in
the window cannot be attributed, `spend.partial: true` and the cockpit renders
the figure as a lower bound. **Spend is never estimated.**

**When budget is checked.** At every stage transition, *and* immediately before
dispatching any agent whose resolved model is the `thinker` alias. The second
check is what makes `per_ticket_warn` actionable: without it the warning could
only arrive after the security gate had already been paid for.

| Threshold | Effect |
|---|---|
| `per_ticket_warn` crossed | Chief reports the running total; cockpit flags amber. Work continues. |
| `per_ticket_stop` crossed | Work stops before dispatching anything further; the owner is asked. |

The cap bounds a *ticket*, not an individual call: one runaway subagent can
overshoot between checks.

---

## 8. Lifecycle

### 8.1 Twelve stages

| # | Stage | What happens |
|---|---|---|
| ① | intake | Owner describes it in any words. Chief classifies. Ticket committed to `main`, `gh issue` opened. |
| ② | triage | Slices loaded, snapshot refreshed. Explorer locates files. **Lane decided.** |
| ③ | design | Architect writes `plan.md`. **Owner checkpoint 1.** |
| ④ | build | Worktree + branch. Implementer writes code and commits. |
| ⑤ | gates | Selected gates in parallel. Findings → fixer, max `max_fix_rounds`. |
| ⑥ | smoke | **The application boots and the change is exercised through it** (§9.6). No `pytest` here — that is the tests gate at ⑤. |
| ⑦ | review | Summary + verdicts + diff. **Owner checkpoint 2.** |
| ⑧ | pr | Pull request opened, model-free gates re-run in CI against the snapshot. |
| ⑨ | staging | Branch deployed to staging. **Owner checkpoint 3.** |
| ⑩ | merge | Owner merges. `main` stays deployable. |
| ⑪ | release | Tag + deploy to production. **Owner checkpoint 4.** |
| ⑫ | close | Ticket archived, issue closed, changelog entry written. |

**⑤ and ⑥ are different work.** The tests gate runs `pytest` and reports
coverage. ⑥ starts the application and exercises the change through it — which
`pytest` need not do, since template rendering is typically untested. A ⑥ failure
is a `Finding` from the `smoke` gate and follows the same recovery path as any
other gate finding (§9.3). One recovery mechanism, not two.

### 8.2 Lanes

| Lane | Stages | Gates permitted at ⑤ |
|---|---|---|
| **fast** | ① ② ④ ⑤ ⑥ ⑦ ⑧ ⑩ ⑪ ⑫ — skips **③ design** and **⑨ staging** | **model-free only**: constitution, size, tests |
| **full** | all twelve | any |

Smoke runs at ⑥ in both lanes and is never selected at ⑤.

**Both lanes include ②**, which decides the lane and loads the slices. A fast
ticket without ② would reach ④ with no `brand` or `ux` slice — the failure mode
G4 exists to prevent, since fast-lane work is the string-and-colour editing those
slices govern.

**Both lanes include ⑥.** A colour fix that is never rendered is not verified.
Every one of the 26 hex-fix tickets is a Jinja/CSS edit `pytest` would not
exercise, so booting the application is the only check that catches a broken
template. ⑥ is model-free and takes seconds.

**Both lanes include ⑪ and ⑫**, so a fast ticket deploys and closes like any
other.

**Checkpoints.** 2 (review) and 4 (release) are **unconditional**. 1 (design) and
3 (staging) are **lane-dependent** and recorded `skipped` on a fast ticket.

**Lane selection at ②, using only what is observable at ②:** `fast` requires
**all** of —

- no file added or deleted
- no schema change (no `migrate_*`, no `CREATE`/`ALTER`/`DROP`)
- no route added or removed
- no dependency change (`requirements*.txt`, `pyproject.toml`)
- no path matching `paths.security_sensitive`
- the explorer reports **one** file to change
- the requested change is a literal, string, style or threshold edit

Anything else is `full`. When in doubt, `full`.

**Re-laning at ④.** Lane selection at ② is a prediction. The ticket is
**promoted to `full`** when the actual diff exceeds
`thresholds.max_fast_lane_lines`, adds or deletes a file, touches a second file,
or **touches any path matching `paths.security_sensitive`**. `lane: full` is
written to `status.yml`, the owner is told, and the ticket re-enters ③. **The
existing diff is kept** and handed to the architect as input; `plan.md` documents
what was already written. A ticket is never demoted from `full` to `fast`.

**Precedence — one rule.** A path matching `paths.security_sensitive` forces
`full` at ② and forces promotion at ④. **The owner cannot override into `fast`
when any changed path matches**; the override is refused, naming the glob.
Consequently the security gate never needs to run on a `fast` ticket — there is
no such ticket. Every other lane rule is overridable.

**Acknowledged gap.** UI-string language lives in the `ux` gate (§9.1), which the
fast lane excludes — yet "add a label to a template" is an archetypal fast
ticket. The mitigation is mechanical and cheap: the constitution gate reports
`constitution.new-ui-literal` at `MEDIUM` for every new user-visible literal in a
changed template (a new text node, or a new `placeholder`/`title`/`aria-label`/
`alt` attribute) when `language.ui != none`. It does not judge the language —
that is not decidable — it simply puts the new string in front of the owner at
⑦. Spanish-only UI is therefore *reviewed* but not *enforced* in the fast lane,
and that is a deliberate trade, not an oversight.

### 8.3 Git conventions

| Rule | Form |
|---|---|
| Branch | `ticket/NNNN-slug`, always. Created by the chief; the owner never types it. |
| Commit | `type(scope): summary` — types `feat` `fix` `refactor` `chore` `docs` `test` `perf`. Shape checked mechanically. |
| Scope | One ticket, one branch, one pull request. |
| `main` | Always deployable. |

This replaces the mixed convention in `cont` (`feat/caja-module` alongside
`feature/shift-control`).

**Note on `v2`:** `cont` has a long-lived `v2` branch. Long-lived branches drift
until merging them becomes its own project. Under Taller, `v2` would become a
series of tickets merged individually. An observation; out of scope.

---

## 9. Gates

### 9.1 Roster

| Gate | Catches | Implementation | Selectable at ⑤ |
|---|---|---|---|
| Constitution | Hardcoded colour/font values outside the brand `tokens.css`; imports violating `paths.layers`; `.md` at repository root; single-use script committed; commit-message shape; new UI literal; stale snapshot; malformed override | **Python** | yes |
| Size | File and function length; duplication | **Python** | yes |
| Tests | `pytest` ran and passed; coverage against `min_coverage_pct` | **Python** | yes |
| Smoke | Application boots; the change is exercised (§9.6) | **Python** | **no — stage ⑥** |
| Security | CSRF, missing `@permission_required`, SQL injection, secrets, transaction safety | `thinker` | yes |
| Code quality | Reuse, dead code, error handling, simplification, judgement calls the constitution linter cannot make | `worker` | yes |
| UX / design | Component conventions, mobile, accessibility, token usage in context, **UI-string language** against `language.ui` | `worker` | yes |

Six gates are selectable at ⑤; **three of those six require no model** —
constitution, size, tests — and those three are exactly the three that run in CI
(§9.4). Smoke is also model-free but belongs to stage ⑥.

The constitution gate is **fully mechanical**: every rule has a decidable test.
Identifying whether a string is Spanish is a heuristic, so that rule lives in the
UX gate. A gate that sometimes needed a model could not honour §9.4's promise of
no per-push cost.

**Mechanical definitions:**

- *Single-use script committed*: a new root file matching `fix_*.py`,
  `check_*.py`, `debug_*.py`, `diagnose_*.py`, `_*.py`, or `test_*.py` outside
  `paths.tests_dir`.
- *`.md` at repository root*: any new root `.md` other than `README.md`,
  `CLAUDE.md`, `CHANGELOG.md`, `LICENSE.md`.
- *Commit-message shape*: `^(feat|fix|refactor|chore|docs|test|perf)(\([a-z0-9-]+\))?: .{1,72}$`.
  The *language* of the summary is not checked.
- *Duplication normalisation*: strip comments and blank lines, collapse runs of
  whitespace to one space, preserve identifiers and literals verbatim. Two blocks
  of ≥ `dup_block_lines` normalised lines that are byte-identical are a
  duplication finding. Identifiers are **not** normalised, so the rule gives the
  same answer locally and in CI and never flags structurally-similar-but-distinct
  code.

### 9.2 Selection at ⑤

| Condition | Gate added |
|---|---|
| always | constitution, size |
| any `.py` changed, or tests exist | tests |
| any path matches `paths.ui` **and lane is `full`** | ux |
| lane is `full` | quality |
| any path matches `paths.security_sensitive` | security — and the lane is `full` by §8.2 |

A fast ticket runs exactly the three model-free gates at ⑤, plus smoke at ⑥. A
typical full ticket runs four or five plus smoke. The `ux` row carries the lane
condition explicitly; without it almost every fast ticket would match
`templates/**` and pull in a `worker` gate the lane forbids.

### 9.3 Severity policy

| Severity | Action |
|---|---|
| `BLOCKER`, `HIGH` | Auto-fix, maximum `thresholds.max_fix_rounds` (2), then stop and escalate |
| `MEDIUM` | Reported in the owner's summary. Never auto-fixed. |
| `LOW`, `NIT` | Logged in the ticket. No action unless the owner asks. |

Applies identically to ⑤ gate findings and the ⑥ smoke gate. The 2-round cap is
the cost control: without it, 12 findings spawn 12 fixes which re-trigger the
gates, recursively.

### 9.4 CI is a backstop, not a second opinion

`.github/workflows/taller-ci.yml` runs **only the three model-free gates** —
constitution, size, `pytest` — loading `.taller/resolved.json` (§4.6) rather than
resolving. No hub, no secrets, no API key, no per-push LLM cost, under a minute.
It replaces `code-review.yml`, `security.yml` and `design-review.yml`.

**The job always runs**, and must not use a workflow-level `paths-ignore`: on
GitHub a required check that never reports leaves the pull request pending
forever, making §13's "require `taller-ci` green" a merge deadlock.

**Two check names, one workflow.** The job's first step classifies the push:

| Push touches | Reports as | Meaning |
|---|---|---|
| only `.taller/work/**/{ticket.md,status.yml,notes.md}` | `taller-ci` ✓ **and** `taller-ci-mode: ticket-files` | Trivially green; no gate ran |
| anything else | `taller-ci` ✓/✗ **and** `taller-ci-mode: full` | Gates ran |

The required check is `taller-ci`, so the pull request never deadlocks. The
second, informational check is what lets `taller doctor` (§15.4) distinguish a
real green from an early exit — without it, the newest run on `main` is almost
always a ticket-file commit and "CI is green" would be vacuous.

### 9.5 Repository scan mode

Each Python gate **except smoke** exposes `scan(tree, ruleset) -> [Finding]`
alongside `run(diff, ruleset)` — the same rules applied to the whole working tree
instead of a diff. Smoke has no tree-wide meaning and is exempt. `taller scan`
drives it, produces the cockpit Health figures (§12), and quantifies the 26 hex
values and 40+ root `.md` files. Phase C.

### 9.6 The smoke gate

The fast lane's safety argument rests on ⑥, so it is specified, not left to the
implementer. Configuration comes from `smoke` in the profile or project
`taller.yml` (§4.1) and is reachable as `RuleSet["smoke"]`.

| `kind` | Behaviour |
|---|---|
| `http` | Run `boot` as a subprocess. Poll `ready` until HTTP 200 or `timeout_s`. GET every URL in `routes`, plus every **mapped route** (below). Any non-2xx/3xx, any unhandled exception in the captured log, or a timeout is a finding. Terminate the subprocess in a `finally`. |
| `import` | Import `module` in a subprocess with `timeout_s`. Any exception is a finding. |
| `none` | Gate reports `result: pass` with `metrics: {skipped: true}`. Declared explicitly, never inferred. |

**Mapped routes** — how "the change is exercised" becomes decidable. At ② the
explorer writes a `template → routes` map for the changed templates into
`status.yml`, derived from `render_template(...)` call sites. The smoke gate GETs
those routes. When a changed template cannot be mapped to any route (an
`{% include %}` partial, or a dynamic name), the gate reports
`smoke.unmapped-template` at `MEDIUM` and falls back to `routes` — so an
unverifiable template is *visible to the owner at ⑦* rather than silently
unchecked.

Rule ids: `smoke.boot-failed` (BLOCKER), `smoke.route-error` (BLOCKER),
`smoke.timeout` (HIGH), `smoke.unmapped-template` (MEDIUM).

### 9.7 Rule ids and default severities

Three mechanisms key off severity — the fixer, the summary, and §4.5's
downgrade — so severity belongs to the rule id, not to the implementer's
judgement. Mechanical gates:

| Rule id | Severity |
|---|---|
| `brand.hardcoded-color` | HIGH |
| `brand.hardcoded-font` | HIGH |
| `constitution.layer-violation` | HIGH |
| `constitution.root-markdown` | MEDIUM |
| `constitution.single-use-script` | MEDIUM |
| `constitution.commit-message-shape` | MEDIUM |
| `constitution.new-ui-literal` | MEDIUM |
| `constitution.resolved-snapshot-stale` | HIGH |
| `constitution.override-without-reason` | HIGH |
| `constitution.override-expired` | HIGH |
| `constitution.override-not-permitted` | BLOCKER |
| `size.file-too-long` | MEDIUM |
| `size.function-too-long` | MEDIUM |
| `size.duplicate-block` | LOW |
| `tests.failed` | BLOCKER |
| `tests.error` | BLOCKER |
| `tests.coverage-below-minimum` | MEDIUM (LOW when `min_coverage_pct` is 0) |
| `smoke.*` | §9.6 |

The three LLM gates assign severity per finding, from guidance in their agent
definition, and their rule ids are declared there. **Every security-gate rule is
non-suppressible** regardless of severity (§4.5).

### 9.8 Amendment, not argument

A gate the owner can talk out of is not a gate. When a rule is wrong, the rule
changes via `/taller:amend`, which commits the amendment and refreshes the
snapshot — or is suppressed with a written reason via `overrides.md` (§4.5).
Gates do not accept justifications at review time. This is the mechanism intended
to prevent the decay visible in `REFACTORING_PLAN.md` →
`REFACTORING_PLAN_ORIGINAL.md` → `CONSOLIDATED_REFACTORING_PLAN.md`.

---

## 10. Components and build order

### 10.1 Plugin layout

```
programas/taller/
├── .claude-plugin/plugin.json
├── pyproject.toml                 console_script: taller = taller.cli:main
├── hooks/session-start.py         injects chief + 00-index.md
├── skills/
│   ├── chief/         onboarding/        ticket/
├── agents/                        nine, matching §6 and §5.1 `models:` exactly
│   ├── scribe.md        explorer.md      architect.md
│   ├── implementer.md   fixer.md         summariser.md
│   └── gate-security.md gate-quality.md  gate-ux.md
├── commands/
│   ├── taller-new.md      taller-status.md    taller-approve.md
│   ├── taller-reject.md   taller-resume.md    taller-amend.md
│   └── taller-onboard.md
├── src/taller/                    THE single implementation (§3.5)
│   ├── cli.py                     argument parsing only
│   ├── constitution.py            resolve() -> RuleSet; snapshot write  (§4.4, §4.6)
│   ├── overrides.py               parse, match, downgrade               (§4.5)
│   ├── registry.py                ~/.taller/projects.json
│   ├── tickets.py                 CRUD, transition, commit_to_main      (§7)
│   ├── locking.py                 project + hub + registry locks        (§10.3)
│   ├── models.py                  alias resolution, probe, fallback
│   ├── spend.py                   transcript parsing, weighting         (§7.5)
│   ├── brands.py                  derive, write, swatch page
│   └── gates/
│       ├── constitution.py  size.py  tests.py  smoke.py
├── cockpit/                       Flask application
├── templates/                     constitution scaffolds, CI workflow, PR template
└── tests/
    ├── fixtures/broken-app/       §15.2
    └── golden/                    §15.3
```

`agents/` contains exactly the nine roles of §6 — no agent file for the four
Python gates.

### 10.2 Unit boundaries

| Unit | Does | Interface | Depends on |
|---|---|---|---|
| `registry.py` | Read/write the project registry | `list_projects()`, `add_project()`, `get_project(path)` | filesystem, `locking` |
| `constitution.py` | Resolve both chains; write and load the snapshot | `resolve(path) -> RuleSet`, `write_snapshot()`, `load_snapshot(path)` | `registry`, `overrides`, filesystem |
| `overrides.py` | Parse `overrides.md`; downgrade matching findings | `parse(text) -> [Override]`, `apply(findings, ruleset) -> [Finding]` | nothing but its arguments |
| `tickets.py` | Create, read, update, list, transition tickets | `create()`, `load(id)`, `save(t)`, `list(p)`, `transition(t, stage)`, `commit_to_main(p, files, msg)` | filesystem, `gh`, `locking` |
| `locking.py` | Serialise writes | `project_lock(p)`, `hub_lock()`, `registry_lock()` — context managers | filesystem |
| `models.py` | Resolve aliases, probe, apply fallback | `resolve(role, ruleset)`, `probe()` | `RuleSet` |
| `spend.py` | Attribute and weight transcript usage | `for_ticket(t) -> Spend` (§7.5) | transcript files |
| `gates/*.py` | Findings for one dimension | `run(diff, ruleset)`; `scan(tree, ruleset)` except smoke | nothing but its arguments |
| `brands.py` | Derive, write and render a brand | `from_css()`, `from_image()`, `write()`, `swatch()` | filesystem |
| `chief` skill | Classify, choose lane, select gates, dispatch | prompt contract; consumes `RuleSet`, writes `status.yml` | all of the above |
| `cockpit` | Render and write ticket state | HTTP; imports the same library as the CLI | `tickets`, `registry`, `constitution`, `spend`, `gates` |

`gates/*.py` and `overrides.py` are pure over their arguments. `resolve()` is
pure over the filesystem. Every unit is testable without the others.

### 10.3 Concurrency

Three locks, all in `locking.py`, all under `~/.taller-run/`:

| Lock | Guards |
|---|---|
| `locks/<project>.lock` | Any read-modify-write of `status.yml` or `notes.md`, and every `commit_to_main()` sequence — two simultaneous `git commit` calls on one repository is the realistic race |
| `.lock` (hub) | Hub amendments, from `/taller:amend` or the cockpit Constitution screen |
| `registry.lock` | `projects.json` writes — `project adopt`, `last seen` |

Every file write inside a lock is an atomic replace: write to a temporary file in
the same directory, then `os.replace`. A writer that cannot take a lock within 5
seconds fails with a clear message rather than waiting or forcing.

### 10.4 Build order

| Phase | Contents | Effort | Delivers |
|---|---|---|---|
| **A** | Hub, `~/.taller-run/`, slice vocabulary, both resolution chains, `overrides.md`, snapshot, `taller.yml` inheritance, onboarding, brands | ~3 sessions | G1, G3, G8 |
| **D** | Tickets, `status.yml`, locking, `commit_to_main` with `sync`, issue mirroring | ~1 session | G5 |
| **B** | Chief, routing, lanes, model roster, `models probe`, `spend.py` | ~2 sessions | G2, G6, G7 |
| **C** | Gates — constitution first, then size/tests/smoke, then the three LLM gates. `scan()` mode. `project adopt` removes the superseded `code-review/`, `security-review/`, `design-review/` directories. | ~2–3 sessions | G4 |
| **F** | GitHub wiring, `taller-ci.yml`, branch ruleset, staging environment | ~1 session | — |
| **E** | Cockpit | ~2–3 sessions | G7 made visible |

Criterion-to-phase mapping lives in **one place only**, §16. This table names
goals, never criterion numbers, so the two cannot drift.

Each phase is independently useful. A and D alone address §1.1 and §1.3. **Each
phase gets its own implementation plan**, written when the previous phase is
complete.

---

## 11. Onboarding

### 11.1 Two entry points, one wizard

`taller project new <name>` and `taller project adopt` run the same question
list. `adopt` arrives with more answers pre-filled.

| Step | Question | Source |
|---|---|---|
| ① | What is this, in your words? | Owner |
| ② | Profile? `[flask-hotel]` · static-tool · python-app · custom | Owner, inferred default |
| ③ | Brand? `[purobeach]` · new brand… · none | Owner, inferred default |
| ④ | What must never break? | **Owner only** — no scan can answer this |
| ⑤ | Confirm derived facts, including the `smoke` configuration | Machine proposes, owner corrects |
| ⑥ | Summary of everything to be created | **Owner approval** |

**Nothing is written into the project before step ⑥.** The single exception is
the resume file at `~/.taller-run/onboarding/<name>.yml`, outside any project.

### 11.2 Derive facts, interview intent

The machine extracts what is observable: stack, dependencies, directory
structure, existing CSS custom properties, route patterns, naming conventions,
test layout, git history, and a candidate `smoke.boot` command (`run_local.py`,
`wsgi.py`, `docker-compose.yml`). It asks the owner only what is not in the code:
purpose, users, what must never break, brand intent, priorities.

For `cont` this is 6–8 questions rather than 40, and the answers are the ones no
repository scan could produce.

### 11.3 Properties

- One question at a time, with a recommended default in brackets.
- Inferred facts are shown for correction rather than requested as input.
- **Resumable** — answers written to `~/.taller-run/onboarding/<name>.yml` as
  given, so a dead session does not restart the interview. Deleted on completion.
- `adopt` diffs the derived local constitution against the hub and **deletes what
  is already shared**, so adoption reduces text rather than adding it.
- `adopt` creates the `main` worktree (§7.3), writes the first snapshot (§4.6),
  and registers the project.
- `adopt` on a project with superseded `code-review/`, `security-review/` or
  `design-review/` directories proposes their removal (Phase C).

---

## 12. Cockpit

Flask 3.0 + Jinja2 + Bootstrap 5, bound to `127.0.0.1`, started with
`taller cockpit`. **No database.** It imports the same library as the CLI,
reads `~/.taller/projects.json`, scans each project's `.taller/work/*/status.yml`,
and calls `gh` for pull request state.

| Screen | Contents |
|---|---|
| Board | Every ticket, every project, in columns by stage ① → ⑫. Checkpoints with `pending` highlighted; tickets with `sync: pending` marked unsynced. |
| Ticket | The ask, the plan, every gate verdict (§7.4), the diff, and approve / reject / change. |
| Spend | `weighted_tokens` by ticket, week and model; currency when `pricing` is set. `partial: true` marked as lower bounds; tickets past `per_ticket_warn` amber. |
| Constitution | Read and edit rules; saving commits the amendment under the hub lock and refreshes affected snapshots. |
| Health | Per project, from `taller scan` (§9.5): stray root files, hardcoded colour/font values, largest files, duplication — plus `tests_run`, `tests_passed`, `coverage_pct` from the latest tests-gate verdict's `metrics` block (§7.4). |

The cockpit **writes the same files the CLI writes**, under the locks in §10.3.
Approving in the browser and approving in the terminal are the same library call
on the same `status.yml`. It is a view and a writer, not a second system.

The onboarding wizard (§11) runs in the cockpit as a web form using the identical
question list, by calling the same library code.

---

## 13. GitHub and staging

| Piece | Specification |
|---|---|
| `.github/workflows/taller-ci.yml` | Three model-free gates against `.taller/resolved.json`. Replaces `code-review.yml`, `security.yml`, `design-review.yml`. Always runs; two check names (§9.4). |
| Pull request template | Generated from `ticket.md` and gate verdicts. |
| Branch protection | Ruleset: require a pull request, require `taller-ci` green. Admin bypass retained for `tickets.commit_to_main()` only. |
| Issue ↔ ticket | Issue opened at ①, referenced by the pull request, closed at ⑫. |

### 13.1 Staging

```bash
taller stage 43        # wraps:
docker compose -p <project>-staging \
  -f docker-compose.yml -f docker-compose.staging.yml up -d
```

Separate project name, separate port, `./data-staging/` holding a **copy** of
production data. Same Caddy, same Basic Auth, reachable over Tailscale.
Production is unreachable from anything on the branch.

**Constraint:** GitHub Actions cannot reach a Tailscale-only private server.
`taller stage` is therefore a CLI command the owner runs on the deployment host,
not a CI job. A self-hosted runner would automate this and is explicitly
deferred: infrastructure to patch and maintain, in exchange for not typing one
command.

### 13.2 Remotes

The `taller` plugin repository and the `~/.taller` hub repository are created
**local-only**. No GitHub remote is created without the owner's explicit
instruction. **Nothing in this design requires a hub remote** — that is what
§4.6's snapshot is for. The hub benefits from a remote for multi-machine sync,
which is the owner's decision to make.

---

## 14. Failure behaviour

| Failure | Behaviour |
|---|---|
| `BLOCKER` survives `max_fix_rounds` | Stop. `stage: blocked`. Escalate with what was attempted and why it failed. Never proceeds quietly. |
| Gate returns `result: error` | Treated as `BLOCKER`, never as a pass. Ticket blocks. |
| Smoke gate fails at ⑥ | A `Finding` like any other; §9.3 recovery. |
| A changed template maps to no route | `smoke.unmapped-template` MEDIUM; surfaced to the owner at ⑦ rather than silently unchecked (§9.6). |
| Model unavailable or overloaded | Fall back per `fallback:`; record the substitution in `status.yml`. No mid-ticket crash. |
| Session dies or context is compacted | Nothing lost. `ticket.md`, `status.yml`, `notes.md` are on `main`. `/taller:resume <id>`. |
| Subagent returns empty or malformed output | One retry, then escalate. No loops. |
| Two tickets touch the same files | Chief warns at **②**, once the explorer has reported files, and offers to combine. Worktrees keep them physically separate regardless. |
| Diff at ④ breaks a fast-lane bound | Promote to `full`, keep the diff, hand it to the architect, re-enter ③ (§8.2). |
| `main` worktree cannot fast-forward | Rebase the ticket-file commits and retry once (§7.3). |
| Push rejected, or commit is local-only | `sync: pending`; cockpit shows unsynced; retried at the next transition; `doctor` reports it (§7.3). |
| Staging deployment fails | Ticket remains at ⑧. Production is not involved. |
| Owner rejects at ⑦ | Verdicts and the reason copied to `main` under `rejected/<timestamp>/`, **then** worktree and branch deleted. Ticket returns to ②. |
| `per_ticket_warn` crossed | Owner told; cockpit amber; work continues. |
| `per_ticket_stop` crossed | Stop before dispatching anything further; ask the owner. |
| Two writers at once | Project, hub or registry lock + atomic replace (§10.3). Loser fails clearly after 5s. |
| Spend cannot be fully attributed | `spend.partial: true`; rendered as a lower bound. Never estimated. |
| `pricing` unset | `spend.cost: null`; the cockpit shows weighted tokens only; `doctor` notes cost is unavailable. |
| Snapshot older than the hub | `constitution.resolved-snapshot-stale` HIGH, locally (§4.6). |
| Hub changed mid-ticket | Each verdict records `hub_sha`. At ⑦ the chief compares every verdict's `hub_sha` against the hub's **current `HEAD`** and warns that rules moved under the ticket. |
| `gh` unauthenticated | Stage ① issue mirroring, ⑧ and ⑫ fail with a clear message. Local stages continue. |
| Owner tries to force `fast` over a security-sensitive path | Refused, naming the matching glob (§8.2). |
| Override malformed, expired, or non-suppressible | Reported per §4.5; suppresses nothing. |
| A gate flags a rule the owner disagrees with | `/taller:amend`, or an override with a written reason. The gate is not overridden at review time. |

---

## 15. Testing

### 15.1 Python is tested as Python

`constitution.py`, `overrides.py`, `registry.py`, `tickets.py`, `locking.py`,
`models.py`, `spend.py`, `brands.py` and
`gates/{constitution,size,tests,smoke}.py` — `pytest`, fast, deterministic.
These are the load-bearing components, and deliberately the ones that are not
prompts.

Particular attention:

- `resolve()`: hub-only; project override; `paths.security_sensitive` append-only
  at both profile and project level (assert neither can remove the hub floor);
  list-replace elsewhere; missing module; unknown profile; `brand: none`; a slice
  provided by three files in profile order.
- Snapshot: `write_snapshot()` then `load_snapshot()` round-trips a `RuleSet`
  including slice text and brand tokens; a stale `hub_sha` produces
  `constitution.resolved-snapshot-stale` locally and **not** in CI mode.
- `overrides.py`: valid suppression downgrades to `NIT` with the reason attached;
  missing reason; expired `until` (distinct rule id from missing reason); a
  `never`-slice rule and a security rule both refused as non-suppressible.
- `spend.py`: recorded transcript fixtures, including one unattributable record
  asserting `partial: true`; `weighted_tokens` differs from `total_tokens` on a
  cache-heavy fixture; `cost` stays `null` when `pricing` is unset.
- `locking.py`: two writers, one wins, the loser fails within 5s, the file
  survives intact.
- `commit_to_main()`: non-fast-forwardable `main` is rebased and succeeds; a
  rejected push leaves `sync: pending` and loses no transition; the next call
  retries the push first.
- `gates/smoke.py`: `kind: http` boot failure, route 500, timeout with the
  subprocess reaped; `kind: import` raising; `kind: none` passing with
  `skipped: true`; an unmappable template producing `smoke.unmapped-template`.

### 15.2 A fixture repository of deliberate violations

`tests/fixtures/broken-app/` — a small, intentionally non-compliant Flask
application containing known violations:

- 3 hardcoded hex values where a token exists
- a route missing `@permission_required`
- a function over `max_function_lines`
- a duplicated block over `dup_block_lines`
- an English string in the UI (caught by the UX gate; and as a *new* literal by
  `constitution.new-ui-literal`)
- a `.md` file at the repository root
- a `fix_thing.py` at root
- an `overrides.md` entry with no reason
- an `overrides.md` entry past its `until`
- an `overrides.md` entry targeting a security rule (must be refused)
- an import violating `paths.layers`
- a template that raises on render (must fail smoke, not `pytest`)
- a stale `resolved.json`

Each gate runs against it and each violation must be caught **by `rule` id and
at the severity declared in §9.7** — detection alone is not enough, because
severity decides whether a fix round is spent.

### 15.3 Golden tickets

Twelve recorded real requests with expected classification, lane, and gate
selection. Must include:

- one promoted from `fast` to `full` at ④ on diff size
- one promoted at ④ because it newly touched a security-sensitive path
- one where forcing `fast` over a security-sensitive path is refused
- one fast ticket asserting the `ux` gate is **not** selected despite matching
  `paths.ui`, and that `constitution.new-ui-literal` fires instead

### 15.4 `taller doctor`

Each check reports pass / fail / **skipped-with-reason**, so doctor is meaningful
before every phase exists:

| Check | Requires |
|---|---|
| `resolve()` succeeds; no unreasoned, expired or non-permitted override | A |
| `resolved.json` present and not stale | A |
| Registry valid; every registered path exists; every `main` worktree present | A/D |
| Every `status.yml` parses; no ticket left `sync: pending` | D |
| Every configured model reachable (`models probe`) | B |
| `pricing` set (advisory — notes that cost is unavailable if not) | B |
| Every Python gate executes; `smoke` configuration valid for the profile; each LLM gate **dry-runs** (prompt assembles, model reachable — no inference) | C |
| Latest `taller-ci` run on `main` with `taller-ci-mode: full` is green (§9.4) | F |

The dry-run rule keeps `taller doctor` free to run.

### 15.5 Acknowledged limitation

The three LLM gates are non-deterministic. Fixture tests reduce the risk; they do
not eliminate it. A gate will occasionally miss a real problem. This is why owner
checkpoint ⑦ exists and why `main` requires green CI — defence in depth rather
than one perfect filter.

---

## 16. Acceptance criteria

**This table is the only phase↔criterion mapping in the document.**

| # | Criterion | Baseline (2026-09-26) | Target | Phase |
|---|---|---|---|---|
| 1 | `cont` always-loaded preamble | ~7,000 tokens | ≤ 800 tokens | A |
| 2 | Front office + Front-office-modules **authored** local content | 9,466 chars each, identical | < 2,000 chars each | A |
| 3 | Ticket resumable after a killed session | not possible | every ticket | D |
| 4 | Tickets with a recorded `weighted_tokens` figure | 0 | every ticket | B |
| 5 | Owner approval checkpoints before production | informal | 2 unconditional + 2 lane-dependent, enforced | B |
| 6 | Unsuppressed `brand.hardcoded-*` findings on `main`, measured by `taller scan` | 26 in `cont` | **does not increase** ticket over ticket | C |
| 7 | Review directories duplicated across projects | 6 projects | 0 | C |
| 8 | `taller scan` produces Health figures for every project | not possible | all registered projects | C |
| 9 | CI workflows per repository | 3 | 1 | F |
| 10 | Staging environment | none | one per Flask project | F |
| 11 | `taller doctor` green on `cont`, no check skipped | n/a | passes | F |

**Criterion 2** counts authored local content — `product.md`, `architecture.md`,
`never.md`, `overrides.md` — and **excludes the generated `00-index.md`** (~40
lines by design) and `resolved.json` (generated). Without those exclusions the
criterion would be arithmetically unreachable.

**Criterion 6** is measured, not assumed: `taller scan` at stage ① and again at
⑫, comparing unsuppressed `brand.hardcoded-color` and `brand.hardcoded-font`
counts. Findings downgraded by an active override (§4.5) are excluded, because
§4.5 exists precisely to admit reasoned exceptions. Phrased as a ratchet rather
than "0", since the 26 pre-existing values are cleared by their own tickets.

**Criterion 11** is Phase F because doctor checks CI (§15.4), which does not
exist until F.

**Consequences, not deliverables** — tracked, not gated on: the 26 existing hex
values in `cont/templates/` and the 40+ root `.md` files in `PuroBeachClub` are
pre-existing. Taller **generates tickets** for them (§2, §18); `taller scan`
counts them and the Health screen shows them trending down.

---

## 17. Decisions and rejected alternatives

| Decision | Rejected | Reason |
|---|---|---|
| Superpowers as the engine, Taller as the addition | Adopt Spec Kit wholesale; build from scratch | Spec Kit is agent-agnostic, so it cannot use Claude Code subagents — the team structure would be lost. It adds a second toolchain (Python CLI + `uv`) and is verbose by design, conflicting with the cost goal. From scratch means re-implementing working brainstorm/plan skills. |
| Tickets as files, GitHub Issues as a mirror | Issues as the store; local SQLite | Agents are the heaviest readers. Files cost no API ceremony and no network. SQLite is a second source of truth that never appears in a pull request diff. |
| **A committed `resolved.json` snapshot** | Give the hub a remote + deploy key; restrict CI to hub-independent checks | CI cannot see a local-only hub, so two of its three gates could not run and no verdict could record `hub_sha`. A snapshot keeps §13.2's local-only default intact, needs no secrets, and makes rule changes visible in the pull request diff. |
| `ticket.md` + `status.yml` + `notes.md` on `main`, via a long-lived `main` worktree, with an explicit `sync` state | Everything on the branch; assuming push always succeeds | In-flight tickets must be visible from `main`; a rejected branch must not destroy its rejection reason; nothing may disturb `cont`'s live SQLite WAL files; and commit+push is not atomic, so the failure had to become visible rather than assumed away. |
| Runtime state in `~/.taller-run/`, outside the hub repo | Locks and worktrees inside `~/.taller/` | A nested worktree lets a hub amendment sweep a project checkout into the hub, and a hub revert can destroy the worktree Taller commits through. |
| Two separate resolution chains — config and slice text | One "later wins" chain over both | Markdown prose cannot set `thresholds`; a single chain misled about precedence and left `paths` with no project override. |
| Slice text appends; only `overrides.md` suppresses, by rule id, with a reason | Project prose overriding hub prose | Append-vs-override was ambiguous on whether a project can delete a hub prohibition. It cannot. |
| `never` and security rules are non-suppressible | All rules overridable | Otherwise `never` does not mean never, and a security BLOCKER could be downgraded to silence. |
| `paths.security_sensitive` append-only, over a hub floor | Lists replace uniformly | A project able to narrow its own security surface would make the mandatory security gate optional. |
| **Rule ids carry default severities (§9.7)** | Severity left to the implementer | The fixer, the summary and §4.5's downgrade all key off severity. Two implementers would have disagreed on whether a hardcoded hex burns a fix round. |
| Constitution gate fully mechanical; UI-language in the UX gate; `constitution.new-ui-literal` as the fast-lane fallback | A `cheap` model pass in the constitution gate; enforcing language mechanically | Language identification is a heuristic, and a gate that sometimes calls a model cannot promise no per-push cost. The fallback surfaces new strings without judging them, which is decidable. |
| **Smoke fully specified: `kind`, boot, ready, timeout, mapped routes** | Leaving "the application boots" to the implementer | The fast lane's entire safety argument rests on ⑥, and "boots" means nothing for a PyInstaller app or a static site. |
| Both lanes include ②, ⑥, ⑪ and ⑫ | Fast lane as a short prefix | ② loads the slices fast work most needs; ⑥ is the only step that renders a template, and fast work is template editing; omitting ⑪/⑫ meant fast tickets never deployed or closed. |
| ⑤ tests gate = `pytest`; ⑥ smoke = boots and exercises | ⑥ re-running `pytest` | They were the same work with two different recovery mechanisms. |
| Override into `fast` over a security-sensitive path is **refused** | The gate runs anyway on a forced-fast ticket | The two rules contradicted each other. Refusal makes the case impossible. |
| Lane is a prediction; re-laned at ④, including on newly-touched security paths | Lane fixed at ② | Diff size and final paths are not observable at ②. |
| `src/taller/` is the single implementation | "The CLI is the single implementation" | `/taller:new` creates a ticket and `taller project new` creates a project. The shared thing is the library. |
| **`weighted_tokens` for budget; `pricing` optional and unshipped** | Raw token sum; shipping a price table | In §7.1's own example 65% of tokens are cache reads, which bill ≈ 0.1×, so a raw sum would fire the budget on context re-reads rather than cost. A shipped price table would go stale and be worse than an honest token count. |
| Budget checked at transitions **and** before `thinker` dispatch | Transitions only | At stage granularity the warning could only arrive after the expensive gate had been paid for. |
| **CI reports two check names** | One check that exits early | An early exit is a successful run, so "CI is green" was vacuous — ticket-file commits are the newest run a dozen times per ticket. The informational check gives doctor something to filter on. |
| `scan()` on every Python gate except smoke | Diff-only gates; `scan()` on smoke too | The Health screen had no producer; smoke has no tree-wide meaning. |
| Security gate on `thinker` | `worker` | Owner's explicit decision. A missed authorisation check is liability. |
| Fable 5.1 unassigned | Assign it to the UX gate | No evidence it outperforms `worker` there. |
| Two-layer model indirection | Model names in agent files | Model availability cannot be enumerated and changes without notice. |
| Staging as a CLI command | Self-hosted GitHub runner | No route from a hosted runner to a Tailscale-only server. |
| Onboarding scratch outside the project | Inside `.taller/` | "Nothing is written before step ⑥" was otherwise false for `project new`. |
| Derive facts, interview intent | Full interview; full auto-derivation | Interview alone re-types what the repository already states. Derivation alone describes what the code *is*, never what was *meant*. |
| Profiles + modules, capped by a two-project rule | One shared constitution; per-project only | Three genuinely different project shapes exist. Unbounded modules become their own maintenance project. |
| Commit-message *shape* checked, not language | Enforce Spanish or English summaries | Shape is decidable; language is not. |
| Local-only repositories initially | Create GitHub remotes now | Publishing is the owner's decision, not a design requirement. |

---

## 18. Out of scope

- Refactoring `PuroBeachClub`, and fixing the 26 existing hex values in `cont`
  (Taller generates tickets for both; it does not do the work as part of its own
  construction)
- Merging or retiring the `cont` `v2` branch
- Multi-user access, authentication, or a hosted cockpit
- Self-hosted CI runners
- Repairing the failing GitHub MCP server (Taller uses `gh`)
- Shipping a model price table
- Any fourth profile or module not required by two existing projects
- A tenth slice
