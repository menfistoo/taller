# Taller — Design Specification

**Date:** 2026-09-26
**Status:** Approved by owner (design phase complete) · revised after spec review
**Owner:** Catia Schubert
**Pilot project:** `C:\Users\catia\cont` (payment-reconciliation)

---

## 0. Document scope and how to read it

This is the **system architecture specification** for Taller: a development
environment that wraps Claude Code so that one orchestrating agent holds project
context and delegates work to specialist agents, through quality gates, under
owner approval, with GitHub as the system of record.

The system has six phases (A–F, section 10.4). All six are specified here because
they share four contracts — the **slice vocabulary** (§4.4), the **`RuleSet`**
(§4.5), the **ticket format** (§7), and the **`Finding`/verdict format** (§7.4).
The cockpit cannot be designed without knowing the ticket format; the gates
cannot be designed without knowing how the constitution resolves. Splitting the
specification would have produced six documents that contradict each other.

**Implementation is not planned here.** Each phase gets its own implementation
plan, written separately, in the order given in §10.4. The first plan to be
written covers **Phase A only**.

**Language:** this document, all code, identifiers, comments, and commit messages
are in English. Application UI strings are in Spanish. This follows the owner's
existing convention.

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
| G3 | Shared rules, declared once | Front office + Front-office-modules local constitutions each < 2,000 chars | A |
| G4 | Enforced conventions | No new hardcoded hex admitted by the gate | C |
| G5 | Work survives session death | Any ticket resumable from disk after a killed session | D |
| G6 | Visible cost | Every ticket records token spend by model | B |
| G7 | Owner keeps final control | 4 approval checkpoints; nothing reaches production unapproved | B (enforced), E (visible) |
| G8 | Uniform across projects | Identical `.taller/` shape, stages, ticket format and commands regardless of stack or brand | A |

### Non-goals

- **Not a replacement for superpowers.** Superpowers remains the brainstorm →
  plan → execute → verify engine. Taller adds what it lacks.
- **Not a persistent daemon.** See §3.1.
- **Not multi-user.** Single operator. No auth in the cockpit; it binds to
  `127.0.0.1`.
- **Not a Spec Kit installation.** Ideas adopted (§17), toolchain not.
- **Not a refactor of existing applications.** Taller may *generate tickets* that
  clean up `PuroBeachClub` or the 26 existing hex values in `cont`; it does not
  perform that cleanup as part of its own construction.

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

**Load by need.** `00-index.md` is a routing map naming **slices** (§4.4), not
files:

| Work touches | Slices loaded |
|---|---|
| Template or CSS | `ux`, `brand` (+ the brand's `tokens.css`) |
| Route or query | `architecture`, `security` |
| New feature | `product`, `architecture`, `conventions` |
| Any path on the security-sensitive list (always) | `security`, `never` |

Every slice named here is defined in §4.4 and provided by a file in §4.1 or §5.

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
| Python 3.11+ | hard | The `taller` CLI, gate scripts, spend accounting and cockpit are Python |
| `gh` CLI, authenticated | hard for D/F | Issue mirroring and PR stages fail with a clear error; local stages still work |
| superpowers | **soft** | Taller falls back to its own minimal plan step |
| Docker Compose | hard for staging only | Stage ⑨ is skipped with a clear message |

Superpowers is a soft dependency so the plugin remains standalone and
transferable.

### 3.5 Command surface

Two surfaces, split by whether a Claude Code session is required.

| Surface | Commands | Why |
|---|---|---|
| **`taller` CLI** (Python console script, installed with the plugin) | `taller new`, `adopt`, `brand new`, `brand edit`, `models probe`, `stage`, `doctor`, `cockpit`, `status` | Run outside a session — from a terminal, a script, or the server. `taller stage` in particular runs on the deployment host. |
| **Slash commands** (in-session) | `/taller:new`, `/taller:approve`, `/taller:resume`, `/taller:amend`, `/taller:status`, `/taller:onboard` | Need the conversation: they dispatch agents and read the owner's intent. |

Overlapping names (`status`, `new`, onboarding) are the **same code**: the slash
command collects intent conversationally and then calls the CLI. The CLI is the
single implementation; slash commands are a front end. No behaviour exists in one
and not the other.

---

## 4. The hub

```
~/.taller/                         git repository
├── taller.yml                     DEFAULT models, effort, budget, thresholds
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
│   ├── language/es-ui.md              → conventions
│   └── never.md                       → never
├── profiles/
│   ├── flask-hotel.yml
│   ├── static-tool.yml
│   └── python-app.yml
└── templates/new-project/         stack skeletons
```

### 4.1 Profiles

A profile names the modules a project inherits, its default brand, and its path
classification.

```yaml
# ~/.taller/profiles/flask-hotel.yml
name: flask-hotel
description: Flask + SQLite WAL + Jinja2 + Bootstrap 5 + Docker + Caddy
modules:
  - stack/flask-sqlite
  - security/web-app
  - conventions/python
  - conventions/js
  - language/es-ui
  - ux/bootstrap-es
  - never
brand: purobeach
paths:
  security_sensitive:          # globs. Force `full` lane; force the security gate.
    - "routes/**"
    - "blueprints/**"
    - "database.py"
    - "**/auth*.py"
    - "**/permissions*.py"
    - "migrate_*.py"
    - "wsgi.py"
    - "docker-compose*.yml"
    - "Caddyfile"
    - ".env*"
  ui:                          # globs. Select the ux gate.
    - "templates/**"
    - "static/**/*.css"
    - "static/**/*.js"
  layers:                      # import rules, checked mechanically
    "routes/**":     ["database", "utils.*"]
    "blueprints/**": ["database", "utils.*"]
    "database.py":   []
```

```yaml
# ~/.taller/profiles/python-app.yml
name: python-app
description: Packaged Python desktop application (PyInstaller)
modules: [stack/python-app, security/minimal, conventions/python, never]
brand: none
paths:
  security_sensitive: ["**/*secret*", ".env*", "build.py", "*.spec"]
  ui: []
  layers: {}
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
palette, type scale and assets, so a brand is reviewed visually rather than as a
list of hex codes.

### 4.3 Slice vocabulary

There are exactly nine slices. This list is closed; adding one is a change to
this specification.

| Slice | Content | Provided by |
|---|---|---|
| `product` | What this does, who uses it, what must never break | **project only** |
| `architecture` | This project's layers and dependency rules | **project only** |
| `stack` | Runtime, framework, database, deployment shape | hub module |
| `conventions` | Naming, DB patterns, routes, code style, UI-string language | hub module(s) |
| `security` | Auth, CSRF, permissions, secrets, transaction safety | hub module |
| `ux` | Component conventions, mobile, accessibility, token usage rules | hub module |
| `brand` | Which token when — plus the brand's `tokens.css` | hub brand |
| `never` | Hard prohibitions | hub module, project may append |
| `overrides` | Project deviations, each with a stated reason | **project only** |

A slice may be provided by **several** module files (e.g. `conventions` comes
from `conventions/python.md`, `conventions/js.md` and `language/es-ui.md`). They
are concatenated in profile order. `product` and `architecture` can never be
inherited — they are what makes a project itself.

### 4.4 Resolution and the `RuleSet`

`constitution.resolve(project_path) -> RuleSet` is Phase A's central contract.

```python
ResolvedSlice = {
    "name":    str,          # one of the nine slice names
    "sources": [str],        # absolute paths, in application order
    "text":    str,          # concatenated content
}

RuleSet = {
    "project":    {"path": str, "profile": str, "name": str},
    "slices":     {slice_name: ResolvedSlice},   # only the nine; absent if unprovided
    "brand":      {"slug": str,                  # or None when brand == "none"
                   "tokens_path": str,
                   "tokens": {str: str}},        # parsed --name -> value
    "paths":      {"security_sensitive": [glob],
                   "ui": [glob],
                   "layers": {glob: [allowed_import]}},
    "thresholds": {str: int},
    "models":     {role: model_id},              # aliases already resolved
    "effort":     {role: str},
    "budget":     {str: int},
    "language":   {"code": "en", "ui": "es", "commits": "en"},
    "hub_sha":    str,
    "overrides":  [{"rule": str, "reason": str, "source": str}],
}
```

**Resolution order** (later wins): hub `taller.yml` → profile → hub modules →
project `taller.yml` → project `constitution/` → project `overrides.md`.

**Conflict rule:** the project wins, but only with a written reason. An entry in
`overrides.md` without a `reason` is itself a constitution-gate violation, and
`resolve()` records it in `overrides` with `reason: None` so the gate can fail it.

**Determinism:** `resolve()` performs no network access and no model calls. It is
pure over the filesystem, so it is directly unit-testable.

`~/.taller/` is a git repository because one edit can affect six projects.
Amendments therefore have history and can be reverted. `hub_sha` is the hub's
`HEAD` at resolution time, and is recorded on every gate verdict (§7.4).

---

## 5. Per-project layout

```
<project>/
├── CLAUDE.md                      stub: points at .taller/constitution/00-index.md
└── .taller/
    ├── taller.yml                 OVERRIDES ONLY — omitted keys come from the hub
    ├── constitution/
    │   ├── 00-index.md            ~40 lines. ALWAYS loaded. Routing map (§3.1).
    │   ├── product.md             slice: product
    │   ├── architecture.md        slice: architecture
    │   ├── never.md               slice: never — OPTIONAL, appends to the hub's
    │   └── overrides.md           slice: overrides
    └── work/
        └── NNNN-slug/             tickets
```

Only `product`, `architecture`, `never` (append) and `overrides` are local. The
other five slices come from the hub. A project with no deviations has a
`taller.yml` of zero lines and an `overrides.md` of zero rules — which is the
target state for Front office and Front-office-modules.

### 5.1 taller.yml

The **hub** file carries the defaults. A project file overrides individual keys
by deep merge; unspecified keys inherit. This is the same inheritance rule as
`constitution/` (§4.4), applied to configuration.

```yaml
# ~/.taller/taller.yml — the defaults for every project
model_aliases:                # the ONLY place a concrete model name appears
  thinker:  opus
  worker:   sonnet
  cheap:    haiku
  creative: fable             # untested; unassigned by decision

models:                       # role -> alias
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
  gate_security: medium
  gate_quality:  medium
  gate_ux:       medium
  default:       low          # applies to every role not named above

fallback: worker              # unreachable model degrades, never crashes

budget:
  per_ticket_warn: 150000
  per_ticket_stop: 400000

thresholds:
  max_file_lines:     800
  max_function_lines: 80
  max_fast_lane_lines: 50
  max_fix_rounds:      2
  min_coverage_pct:    0      # 0 = report only, do not fail
```

```yaml
# <project>/.taller/taller.yml — e.g. cont, which is stricter about file size
thresholds:
  max_file_lines: 400
```

Two layers of indirection mean a new model release is **one line in
`model_aliases`** instead of one edit per agent file. `fallback` means a model
name the account cannot reach degrades to `worker` rather than failing
mid-ticket.

**There is no `chief` key, deliberately.** The chief is the owner's own session,
and Taller cannot set the model of the session it is running inside. See §6.1.

---

## 6. Model roster

Nine agent roles. Three gates have no agent at all.

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

Constitution, size and tests gates are Python and take no model (§9.1).

### 6.1 The chief's model

The chief runs in the owner's session, so its model is whatever the owner
selected. Taller cannot change it. Instead, `/taller:new` reads the session model
from the transcript (`message.model`, §7.5) and warns when it is mismatched:

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
.taller/work/0043-date-filter/
├── ticket.md          the owner's words, verbatim, plus the classification
├── status.yml         machine state
├── notes.md           decisions and WHY, including rejection reasons
├── plan.md            full lane only
└── gates/             one verdict file per gate that ran
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
created: 2026-09-26T10:14:00
gates: [constitution, size, tests]
verdicts:
  constitution: {result: pass, blocker: 0, high: 0, medium: 0, low: 0, hub_sha: a3f9c21}
  size:         {result: pass, blocker: 0, high: 0, medium: 0, low: 0, hub_sha: a3f9c21}
  tests:        {result: pass, blocker: 0, high: 0, medium: 0, low: 2, hub_sha: a3f9c21}
fix_rounds: 1
checkpoints:
  design:  skipped
  review:  pending
  staging: n/a
  release: pending
spend:
  partial: false
  by_model:
    claude-haiku-4-5-20251001: {input: 41200, output: 3100}
    claude-sonnet-5:           {input: 88400, output: 12600}
  total_output: 15700
```

This example is a `fast` ticket, so its gates are the three model-free ones
(§8.2). A `full` ticket's `gates` list would additionally contain `security`,
`quality` and/or `ux`.

### 7.2 What lives where

| File | Branch | Written at | Reason |
|---|---|---|---|
| `ticket.md` | **`main`** | ① | The ticket must be visible from `main` or the cockpit reports nothing |
| `status.yml` | **`main`** | ① and every stage transition | Same; also the resume key |
| `notes.md` | **`main`** | ① onward | §14 relies on it surviving branch deletion |
| `plan.md` | branch | ③ | Belongs to the work; merges with the PR |
| `gates/*.md` | branch | ⑤ | Belongs to the work; merges with the PR |

**On rejection at ⑦** the gate verdict files and the owner's reason are copied to
`main` under `work/NNNN-slug/rejected/<timestamp>/` **before** the worktree and
branch are deleted. Nothing that justified a rejection is ever destroyed by the
cleanup that follows it.

### 7.3 Ticket creation and branch protection

1. Creating a ticket commits `ticket.md`, `status.yml` and `notes.md` **directly
   to `main`**.
2. Work happens on `ticket/NNNN-slug`, in a git worktree.
3. `plan.md` and `gates/` land on the branch and merge with the pull request.
4. The cockpit reads `main` for the ticket list and `gh pr list` for in-flight
   state.

`main` requires a pull request, with the owner's admin bypass retained and used
**only** for the stage-① and stage-transition commits to the three `main`-side
files above. Branch protection that blocks the sole developer produces fights
with the tooling, not safety. The CI workflow skips when a push touches only
`.taller/work/**/{ticket.md,status.yml,notes.md}`.

### 7.4 `Finding` and verdict format

Four consumers depend on this: `gates/*.py` produce it, the fixer consumes
severities, the summariser condenses it, the cockpit renders it.

```python
Finding = {
    "gate":     str,     # constitution | security | quality | size | ux | tests
    "severity": str,     # BLOCKER | HIGH | MEDIUM | LOW | NIT
    "rule":     str,     # stable id, e.g. "brand.hardcoded-color"
    "file":     str,     # repo-relative
    "line":     int,     # 1-indexed; 0 when file-level
    "message":  str,     # one sentence
    "fix_hint": str,     # optional; what a fixer should do
}
```

`gates/<name>.md` is YAML front matter plus a Markdown body:

```markdown
---
gate: constitution
result: fail            # pass | fail | error
hub_sha: a3f9c21
ran_at: 2026-09-26T10:31:00
counts: {blocker: 0, high: 3, medium: 1, low: 0, nit: 0}
findings:
  - {severity: HIGH, rule: brand.hardcoded-color, file: templates/dia.html,
     line: 88, message: "#dc3545 duplicates --app-danger",
     fix_hint: "replace with var(--app-danger)"}
---

Prose explanation for the owner, written by the summariser.
```

`status.yml` stores only the counts and `result` per gate (§7.1) — the findings
themselves stay in `gates/`. `result: error` means the gate could not run; it is
treated as `BLOCKER` for flow purposes and never as a pass.

### 7.5 Spend accounting

Claude Code writes a session transcript at
`~/.claude/projects/<slug>/<session>.jsonl`. Each assistant record carries
`message.model` and a full `message.usage` (`input_tokens`,
`cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`), plus
`timestamp`, `gitBranch`, `agentName` and `isSidechain`. This is verified against
a live transcript, not assumed.

`lib/spend.py` attributes usage to a ticket by:

1. **`gitBranch`** where present — every ticket owns a branch, so this is exact.
2. **Stage-transition time window** otherwise, for records written before the
   branch exists (stages ① and ②).

`spend.by_model` keys are the concrete model ids as reported, not aliases, so the
record stays truthful when an alias is remapped or a `fallback` fires. If any
record in the window cannot be attributed, `spend.partial: true` is set and the
cockpit renders the figure as a lower bound. **Spend is never estimated.**

`budget.per_ticket_stop` is checked at each stage transition, because that is when
the transcript is parsed. A single runaway subagent can therefore overshoot the
cap before it is noticed; the cap bounds a *ticket*, not an individual call.

---

## 8. Lifecycle

### 8.1 Twelve stages

| # | Stage | What happens |
|---|---|---|
| ① | intake | Owner describes it in any words. Chief classifies. Ticket committed to `main`, `gh issue` opened. |
| ② | triage | Slices loaded. Explorer locates files. **Lane decided.** |
| ③ | design | Architect writes `plan.md`. **Owner checkpoint 1.** |
| ④ | build | Worktree + branch. Implementer writes code and commits. |
| ⑤ | gates | Selected gates in parallel. Findings → fixer, max `max_fix_rounds`. |
| ⑥ | verify | `pytest` runs, application boots, change is exercised. |
| ⑦ | review | Summary + verdicts + diff. **Owner checkpoint 2.** |
| ⑧ | pr | Pull request opened, model-free gates re-run in CI. |
| ⑨ | staging | Branch deployed to staging. **Owner checkpoint 3.** |
| ⑩ | merge | Owner merges. `main` stays deployable. |
| ⑪ | release | Tag + deploy to production. **Owner checkpoint 4.** |
| ⑫ | close | Ticket archived, issue closed, changelog entry written. |

Staging deploys from the **branch, before merge**, so owner approval means the
change was seen running, not merely read as a diff.

### 8.2 Lanes

| Lane | Stages | Gates permitted |
|---|---|---|
| **fast** | ① ② ④ ⑤ ⑦ ⑧ ⑩ ⑪ ⑫ — skips ③ design, ⑥ verify, ⑨ staging | **model-free only** (constitution, size, tests) |
| **full** | all twelve | any |

Both lanes include **②**, because ② is where the lane is decided and where the
slices are loaded. A fast ticket without ② would reach ④ with no `brand` or `ux`
slice — which is exactly the failure mode G4 exists to prevent, since fast-lane
work is precisely the string-and-colour editing those slices govern.

Both lanes include **⑪ release** and **⑫ close**. A fast ticket deploys and
closes like any other; all four owner checkpoints exist in both lanes, with ①
design and ⑨ staging recorded as `skipped` rather than absent.

**Lane selection at ②, using only what is observable at ②:**

`fast` requires **all** of —

- no file added or deleted
- no schema change (no `migrate_*`, no `CREATE`/`ALTER`/`DROP`)
- no route added or removed
- no dependency change (`requirements*.txt`, `pyproject.toml`)
- no path matching `paths.security_sensitive`
- the explorer reports **one** file to change
- the requested change is a literal, string, style or threshold edit

Anything else is `full`. When in doubt, `full`.

**Re-laning at ④.** Lane selection at ② is a prediction. If the diff produced at
④ exceeds `thresholds.max_fast_lane_lines`, or adds a file, or touches a second
file, the ticket is **promoted to `full`** automatically: `lane: full` is written
to `status.yml`, the owner is told, and the ticket re-enters ③ design. A ticket is
never demoted from `full` to `fast`.

**Precedence — the security gate outranks the lane.** If any changed path matches
`paths.security_sensitive`, the security gate runs, on `thinker`, even if the
owner forced `fast`. The owner cannot override into a lane that skips it; the
override is refused with the matching glob named. Every other lane rule is
overridable.

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
series of tickets merged individually. Recorded as an observation; out of scope.

---

## 9. Gates

### 9.1 Roster

| Gate | Catches | Implementation |
|---|---|---|
| Constitution | Hardcoded colour/font values outside the brand `tokens.css`; layer violations against `paths.layers`; `.md` in repository root; single-use scripts committed; UI string not in `language.ui`; an `overrides.md` entry with no reason | **Python only** |
| Size | File and function length against `thresholds`; duplication | **Python only** |
| Tests | `pytest` ran, passed, exercised the change; coverage reported against `min_coverage_pct` | **Python only** |
| Security | CSRF, missing `@permission_required`, SQL injection, secrets, transaction safety | `thinker` |
| Code quality | Reuse, dead code, error handling, simplification, judgement calls the constitution linter cannot make mechanically | `worker` |
| UX / design | Component conventions, mobile, accessibility, token usage in context | `worker` |

**Three of six require no model**, and those three are exactly the three that run
in CI (§9.4). The constitution gate is deliberately **fully mechanical** — every
rule above has a decidable test. Anything requiring judgement belongs to the code
quality gate, not here. A gate that sometimes needs a model could not honour
§9.4's promise of no per-push cost.

**Mechanical definitions** for the two rules that would otherwise be judgement
calls:

- *Single-use script committed*: a new file at repository root matching
  `fix_*.py`, `check_*.py`, `debug_*.py`, `diagnose_*.py`, `_*.py`, or
  `test_*.py` outside the configured test directory.
- *`.md` in repository root*: any new `.md` at root other than `README.md`,
  `CLAUDE.md`, `CHANGELOG.md`, `LICENSE.md`.

### 9.2 Selection

The chief selects gates by the paths a change touched:

| Condition | Gate added |
|---|---|
| always | constitution, size |
| any `.py` changed, or tests exist | tests |
| any path matches `paths.security_sensitive` | **security — mandatory, §8.2** |
| any path matches `paths.ui` | ux |
| lane is `full` | quality |

A typical fast ticket runs three model-free gates; a typical full ticket runs
four or five.

### 9.3 Severity policy

| Severity | Action |
|---|---|
| `BLOCKER`, `HIGH` | Auto-fix, maximum `thresholds.max_fix_rounds` (2), then stop and escalate |
| `MEDIUM` | Reported in the owner's summary. Never auto-fixed. |
| `LOW`, `NIT` | Logged in the ticket. No action unless the owner asks. |

The 2-round cap is the cost control: without it, 12 findings spawn 12 fixes which
re-trigger the gates, recursively.

### 9.4 CI is a backstop, not a second opinion

`.github/workflows/taller-ci.yml` runs **only the three model-free gates** —
constitution, size, `pytest`. No API key, no per-push LLM cost, under a minute.
It replaces the existing `code-review.yml`, `security.yml` and
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
├── pyproject.toml                 console_script: taller = taller.cli:main
├── hooks/session-start.py         injects chief + 00-index.md
├── skills/
│   ├── chief/                     classify → lane → slices → dispatch
│   ├── onboarding/                derive facts, interview intent, write constitution
│   └── ticket/                    create · resume · close
├── agents/                        nine, matching §6 exactly
│   ├── scribe.md        explorer.md      architect.md
│   ├── implementer.md   fixer.md         summariser.md
│   └── gate-security.md gate-quality.md  gate-ux.md
├── commands/                      slash commands (§3.5)
│   ├── taller-new.md      taller-status.md    taller-approve.md
│   ├── taller-resume.md   taller-amend.md     taller-onboard.md
├── src/taller/
│   ├── cli.py                     the `taller` executable (§3.5)
│   ├── constitution.py            resolve() -> RuleSet          (§4.4)
│   ├── registry.py                ~/.taller/projects.json
│   ├── tickets.py                 read/write ticket folders     (§7)
│   ├── models.py                  alias resolution, probe, fallback
│   ├── spend.py                   transcript parsing            (§7.5)
│   ├── brands.py                  derive, write, swatch page
│   └── gates/
│       ├── constitution.py  size.py  tests.py
├── cockpit/                       Flask application
├── templates/                     constitution scaffolds, CI workflow, PR template
└── tests/
    ├── fixtures/broken-app/       §15.2
    └── golden/                    §15.3
```

`agents/` contains exactly the nine roles in §6 — no `gate-constitution.md`,
because that gate has no model.

### 10.2 Unit boundaries

| Unit | Does | Interface | Depends on |
|---|---|---|---|
| `registry.py` | Read/write the project registry | `list_projects()`, `add_project()`, `get_project(path)` | filesystem |
| `constitution.py` | Resolve hub + profile + modules + project + overrides | `resolve(path) -> RuleSet` (§4.4) | `registry`, filesystem |
| `tickets.py` | Create, read, update, list tickets | `create()`, `load(id)`, `save(t)`, `list(project)`, `transition(t, stage)` | filesystem, `gh` |
| `models.py` | Resolve aliases, probe, apply fallback | `resolve(role, ruleset) -> model_id`, `probe()` | `RuleSet` |
| `spend.py` | Attribute transcript usage to a ticket | `for_ticket(t) -> Spend` (§7.5) | transcript files |
| `gates/*.py` | Each returns findings for one dimension | `run(diff, ruleset) -> [Finding]` (§7.4) | nothing but its arguments |
| `brands.py` | Derive, write and render a brand | `from_css()`, `from_image()`, `write()`, `swatch()` | filesystem |
| `chief` skill | Classify, choose lane, select gates, dispatch | prompt contract; consumes `RuleSet`, writes `status.yml` | all of the above |
| `cockpit` | Render and write ticket state | HTTP; reads/writes the same files as the CLI | `tickets`, `registry`, `constitution`, `spend` |

`gates/*.py` take a diff and a `RuleSet` and return `[Finding]` — no filesystem
or network assumptions, so each is unit-testable in isolation. `resolve()` is
pure over the filesystem (§4.4).

### 10.3 Concurrency

The cockpit and the CLI write the same `status.yml`. Every write is
**read–modify–write under an exclusive lock** on `status.yml.lock`, followed by
an atomic replace (write to a temporary file in the same directory, then
`os.replace`). A writer that cannot take the lock within 5 seconds fails with a
clear message rather than waiting or forcing.

### 10.4 Build order

| Phase | Contents | Effort | Delivers |
|---|---|---|---|
| **A** | Hub, slice vocabulary, `resolve()`, `taller.yml` inheritance, onboarding (`new` + `adopt`), brands | ~3 sessions | G1, G3, G8. Criteria 1, 3 |
| **D** | Tickets, `status.yml`, locking, issue mirroring | ~1 session | G5. Criterion 7 |
| **B** | Chief, routing, model roster, `models probe`, `spend.py` | ~2 sessions | G2, G6, G7 (enforced). Criterion 8, 10 |
| **C** | Gates — constitution linter first, then size/tests, then LLM gates. `adopt` removes the superseded `code-review/`, `security-review/`, `design-review/` directories. | ~2–3 sessions | G4. Criteria 5, 9 |
| **F** | GitHub wiring, `taller-ci.yml`, staging environment | ~1 session | Criteria 4, 9 |
| **E** | Cockpit | ~2–3 sessions | G7 (visible). Criterion 6 visibility |

Each phase is independently useful. A and D alone address §1.1 and §1.3.
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
- **Resumable** — answers are written to `.taller/.onboarding.yml` as they are
  given, so a dead session does not restart the interview.
- `adopt` diffs the derived local constitution against the hub and **deletes what
  is already shared**, so adoption reduces text rather than adding it.
- `adopt` on a project with superseded `code-review/`, `security-review/` or
  `design-review/` directories proposes their removal (Phase C).

---

## 12. Cockpit

Flask 3.0 + Jinja2 + Bootstrap 5, bound to `127.0.0.1`, started with
`taller cockpit`. **No database.** It reads `~/.taller/projects.json`, scans each
project's `.taller/work/*/status.yml`, and calls `gh` for pull request state.

| Screen | Contents |
|---|---|
| Board | Every ticket, every project, in columns by stage ① → ⑫. Owner checkpoints highlighted when waiting. |
| Ticket | The ask, the plan, every gate verdict (§7.4), the diff, and approve / reject / change. |
| Spend | Tokens by ticket, week and model. `partial: true` figures marked as lower bounds. |
| Constitution | Read and edit rules; saving commits the amendment. |
| Health | Per project: stray root files, hardcoded hex count, largest files, test pass rate and coverage (from the tests gate, §9.1). |

The cockpit **writes the same files the CLI writes**, under the locking rule in
§10.3. Approving in the browser and approving in the terminal are the same
operation on the same `status.yml`. It is a view and a writer, not a second
system.

The onboarding wizard (§11) runs in the cockpit as a web form using the identical
question list, by calling the same CLI code (§3.5).

---

## 13. GitHub and staging

| Piece | Specification |
|---|---|
| `.github/workflows/taller-ci.yml` | The three model-free gates only. Replaces `code-review.yml`, `security.yml`, `design-review.yml`. Skipped for pushes touching only the three `main`-side ticket files (§7.3). |
| Pull request template | Generated from `ticket.md` and gate verdicts. |
| Branch protection | Ruleset: require a pull request, require `taller-ci` green. Admin bypass retained for the `main`-side ticket files only. |
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
There is no route from a hosted runner. `taller stage` is therefore a CLI command
the owner runs on the deployment host (§3.5), not a CI job. A self-hosted runner
would automate this and is explicitly deferred: it adds infrastructure to patch
and maintain for the sake of not typing one command.

### 13.2 Remotes

The `taller` plugin repository and the `~/.taller` hub repository are created
**local-only**. No GitHub remote is created without the owner's explicit
instruction. Nothing in this design requires a remote; the hub benefits from one
for multi-machine sync, which is the owner's decision to make.

---

## 14. Failure behaviour

| Failure | Behaviour |
|---|---|
| `BLOCKER` survives `max_fix_rounds` | Stop. `stage: blocked`. Escalate with what was attempted and why it failed. Never proceeds quietly. |
| Gate returns `result: error` | Treated as `BLOCKER`, never as a pass. Ticket blocks. |
| Model unavailable or overloaded | Fall back per `fallback:`; record the substitution in `status.yml`. No mid-ticket crash. |
| Session dies or context is compacted | Nothing lost. `ticket.md`, `status.yml` and `notes.md` are on `main`. `/taller:resume <id>`. |
| Subagent returns empty or malformed output | One retry, then escalate. No loops. |
| Two tickets touch the same files | Chief warns at ① and offers to combine. Worktrees keep them physically separate regardless. |
| Tests fail at ⑥ | Return to ④, maximum `max_fix_rounds`, then `blocked`. |
| Diff at ④ exceeds the fast-lane bound | Promote to `full`, tell the owner, re-enter ③ (§8.2). |
| Staging deployment fails | Ticket remains at ⑧. Production is not involved. |
| Owner rejects at ⑦ | Verdicts and the owner's reason copied to `main` under `rejected/<timestamp>/`, **then** worktree and branch deleted. Ticket returns to ②. |
| `budget.per_ticket_stop` exceeded | Stop at the next stage transition and ask the owner (§7.5 states the granularity). |
| Cockpit and CLI write at once | Exclusive lock + atomic replace (§10.3). Loser fails with a clear message after 5s. |
| Spend cannot be fully attributed | `spend.partial: true`; rendered as a lower bound. Never estimated. |
| Hub rules change mid-ticket | Verdicts record `hub_sha`. A mismatch at ⑦ warns the owner that rules moved under the ticket. |
| `gh` unauthenticated | Stage ① issue mirroring, ⑧ and ⑫ fail with a clear message. Local stages continue. |
| Owner tries to force `fast` over a security-sensitive path | Refused, naming the matching glob (§8.2). |
| A gate flags a rule the owner disagrees with | `/taller:amend`. The rule changes; the gate is not overridden. |

---

## 15. Testing

### 15.1 Python is tested as Python

`constitution.py`, `registry.py`, `tickets.py`, `models.py`, `spend.py`,
`brands.py` and `gates/{constitution,size,tests}.py` — `pytest`, fast,
deterministic. These are the load-bearing components, and they are deliberately
the ones that are not prompts.

`resolve()` gets particular attention: hub-only, project-override, override
without a reason, missing module, unknown profile, `brand: none`, and a slice
provided by three files in profile order.

`spend.py` is tested against recorded transcript fixtures, including one with an
unattributable record to assert `partial: true`.

### 15.2 A fixture repository of deliberate violations

`tests/fixtures/broken-app/` — a small, intentionally non-compliant Flask
application containing known violations:

- 3 hardcoded hex values where a token exists
- a route missing `@permission_required`
- a function over `max_function_lines`
- an English string in the UI
- a `.md` file in the repository root
- a `fix_thing.py` at root
- an `overrides.md` entry with no reason
- an import violating `paths.layers`

Each gate runs against it and each violation must be caught, by `rule` id. This
is a **regression suite for prompts**: editing `gate-security.md` such that it
stops catching the missing decorator turns a test red. Without this, prompt
quality drifts silently.

### 15.3 Golden tickets

Twelve recorded real requests with their expected classification, lane, and gate
selection — asserting the chief routes correctly. Includes at least one that must
be **promoted** from `fast` to `full` at ④, and one where the owner's attempt to
force `fast` over a security-sensitive path must be refused.

### 15.4 `taller doctor`

Checks: `resolve()` succeeds with no unreasoned override, every gate executes,
every configured model is reachable, CI is green, the registry is valid, every
registered path exists, and every ticket's `status.yml` parses.

### 15.5 Acknowledged limitation

The three LLM gates are non-deterministic. Fixture tests reduce the risk; they do
not eliminate it. A gate will occasionally miss a real problem. This is why owner
checkpoint ⑦ exists and why `main` requires green CI — defence in depth rather
than one perfect filter.

---

## 16. Acceptance criteria

| # | Criterion | Baseline (2026-09-26) | Target | Phase |
|---|---|---|---|---|
| 1 | `cont` always-loaded preamble | ~7,000 tokens | ≤ 800 tokens | A |
| 2 | **New** hardcoded hex admitted by the gate | unmeasured | 0 | C |
| 3 | Front office + Front-office-modules local constitutions | 9,466 chars each, identical | < 2,000 chars each | A |
| 4 | CI workflows per repository | 3 | 1 | F |
| 5 | Review directories duplicated across projects | 6 projects | 0 | C (removed by `adopt`) |
| 6 | Tickets with a recorded spend figure | 0 | every ticket | B |
| 7 | Ticket resumable after a killed session | not possible | every ticket | D |
| 8 | Owner approval checkpoints before production | informal | 4, enforced | B |
| 9 | Staging environment | none | one per Flask project | F |
| 10 | `taller doctor` green on `cont` | n/a | passes | C |

**Consequences, not deliverables** — tracked but not gated on:

- The 26 existing hardcoded hex values in `cont/templates/` and the 40+ root
  `.md` files in `PuroBeachClub` are pre-existing. Taller **generates tickets**
  for them (§2 non-goals, §18). Criterion 2 therefore measures *new* violations;
  the existing ones are visible on the cockpit Health screen and trend down as
  those tickets close.

---

## 17. Decisions and rejected alternatives

| Decision | Rejected | Reason |
|---|---|---|
| Superpowers as the engine, Taller as the addition | Adopt Spec Kit wholesale; build everything from scratch | Spec Kit is agent-agnostic, so it cannot use Claude Code subagents — the team structure would be lost. It adds a second toolchain (Python CLI + `uv`) and is verbose by design, conflicting with the cost goal. Building from scratch means re-implementing working brainstorm/plan skills. |
| Tickets as files, GitHub Issues as a mirror | Issues as the store; local SQLite | Agents are the heaviest readers. Files cost no API ceremony and no network. SQLite is a second source of truth that never appears in a pull request diff. |
| `ticket.md` + `status.yml` + `notes.md` on `main` | Everything on the branch | Otherwise in-flight tickets are invisible from `main`, the cockpit reports nothing, and deleting a rejected branch destroys the rejection reason. |
| Constitution gate fully mechanical, no model | A `cheap` model pass inside it | A gate that sometimes calls a model cannot honour §9.4's promise of no per-push cost. Judgement moves to the quality gate. |
| Nine closed slices, modules declare which they provide | Free-form context files | The routing table in §3.1 must name something that provably exists. |
| Both lanes include ②, ⑪ and ⑫ | Fast lane as a short prefix of the full lane | ② decides the lane and loads the slices fast work most needs; omitting ⑪/⑫ meant fast tickets never deployed and never closed. |
| Lane is a prediction, re-laned at ④ | Lane fixed at ② | Diff size is not observable at ②. |
| Security gate outranks the lane | Owner override wins everywhere | Two rules contradicted each other; this resolves it in favour of the liability. |
| `taller.yml` at hub with project override | Per-project only | Per-project only duplicated the roster into every project, contradicting both the hub principle and the "one line" claim. |
| Spend from transcript `usage`, by `gitBranch` | Estimation; hook payloads | Verified present in a live transcript. Every ticket owns a branch, so attribution is exact. Estimation would make G6 a guess. |
| CLI is the implementation, slash commands a front end | Two implementations; slash-only | `taller stage` must run on the deployment host, outside any session. |
| Security gate on `thinker` | `worker` | Owner's explicit decision. A missed authorisation check is liability. |
| Fable 5.1 unassigned | Assign it to the UX gate | No evidence it outperforms `worker` there. |
| Two-layer model indirection | Model names in agent files | Model availability cannot be enumerated and changes without notice. |
| Staging as a CLI command | Self-hosted GitHub runner | No route from a hosted runner to a Tailscale-only server. |
| Constitution amended, never argued with | Gates accept justifications | A gate that can be talked out of is not a gate. |
| Derive facts, interview intent | Full interview; full auto-derivation | Interview alone re-types what the repository already states. Derivation alone describes what the code *is*, never what was *meant*. |
| Profiles + modules, capped by a two-project rule | One shared constitution; per-project only | Three genuinely different project shapes exist. Unbounded modules become their own maintenance project. |
| Commit messages in English | Spanish | Consistent with the existing code/comment convention. |
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
- Any fourth profile or module not required by two existing projects
- A tenth slice
