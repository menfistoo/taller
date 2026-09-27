# Taller — Design Specification

**Date:** 2026-09-26
**Status:** Approved by owner (design phase complete) · revised after spec review, iteration 3
**Owner:** Catia Schubert
**Pilot:** a throwaway greenfield project first, then one existing repository (§10.4)

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
are in English. **The application's own UI language is configuration, not a
constant** — asked at `taller setup` and stored as `language.ui` (§5.1). This
specification uses English throughout; the tool has no opinion.

---

## 1. Problem statement

Taller addresses five problems that appear in any estate of several projects
built with an AI coding agent. **Appendix A** quantifies each one against a real
estate of ten repositories, as evidence that they are real rather than
hypothetical. That appendix is an example, not the scope: Taller ships knowing
nothing about any particular estate (§4.0).

### 1.1 Context is re-declared per project

Each project carries its own `CLAUDE.md` describing a stack, conventions and
security rules that are largely identical across projects sharing that stack. The
file is loaded in full at the start of every session and into every subagent that
reads it. A CSS fix loads the security policy; a database migration loads the
brand rules. Nothing is loaded by need.

*Measured: 8 files, 143,487 characters, of which two are byte-identical; the
largest is ~7,000 tokens of preamble before the first word is typed (A.1).*

### 1.2 Review infrastructure is copied, not shared

Review agent definitions and CI workflows are copied into each repository, then
drift independently. Improving one improves one.

*Measured: `code-review/`, `security-review/` and `design-review/` duplicated
across six projects (A.2).*

### 1.3 Sessions have no memory, so work has no home

An agent session cannot remember the previous one, so each invents its own filing
system: plan documents at the repository root, single-use scripts beside
application code, and no durable record of what was decided or why.

*Measured: 40+ ad-hoc planning documents and ~60 single-use `fix_*.py` /
`check_*.py` / `debug_*.py` scripts in one repository root (A.3).*

### 1.4 Rules exist but nothing enforces them

Conventions are written down and bypassed, because nothing mechanical checks
them. Design tokens are defined and then duplicated as literal values a few files
away.

*Measured: seven CSS custom properties defined, and 26 hardcoded hex values in
templates — three of which duplicate tokens that already exist (A.4).*

### 1.5 No staging environment

Changes go from a branch to production with no intermediate place to exercise
them, so "approved" means a diff was read rather than a running application was
seen.

*Measured: zero occurrences of "staging" across ten repositories (A.5).*

---

## 2. Goals and non-goals

### Goals

Every goal is stated so that it can be measured on **any** project, not on a
particular one.

| # | Goal | Measured by | Phase |
|---|---|---|---|
| G0 | **A new project starts correct** | `taller project new` produces a repository that passes every `doctor` check its phase provides, carries its first tickets, and (from Phase C) boots under the smoke gate | A, completed in C |
| G1 | Cut always-loaded context | Any adopted project's always-loaded preamble ≤ 800 tokens | A |
| G2 | One orchestrator the owner talks to | Owner states intent once per ticket | B |
| G3 | Shared rules, declared once | Any two projects on the same profile each have < 2,000 characters of authored local content | A |
| G4 | Enforced conventions | No new unsuppressed hardcoded colour or font value reaches `main` | C |
| G5 | Work survives session death | Any ticket resumable from disk after a killed session | D |
| G6 | Visible cost | Every ticket records weighted token spend by model | B |
| G7 | Owner keeps final control | Checkpoints 2 (review) and 4 (release) unconditional; 1 (design) and 3 (staging) lane-dependent. Nothing reaches production unapproved. | B |
| G8 | Uniform across projects | Identical `.taller/` shape, stages, ticket format and commands regardless of stack, brand or language | A |
| G9 | **Knows nothing about its owner until told** | The plugin repository contains no occurrence of the domain vocabulary list (§15.6); a fresh hub is empty (§4.0) | A |

### Non-goals

- **Not a replacement for superpowers.** Superpowers remains the brainstorm →
  plan → execute → verify engine. Taller adds what it lacks.
- **Not a persistent daemon.** `taller` runs in the foreground, advances a ticket
  and exits. The chief's continuity comes from a stored session id and from files
  (§3.1, §7.6), not from a resident process.
- **Not multi-user.** Single operator. No auth in the cockpit; it binds to
  `127.0.0.1`.
- **Not a Spec Kit installation.** Ideas adopted (§17), toolchain not.
- **Not a refactor of existing applications.** On adoption Taller *generates
  tickets* for the violations it finds; it does not perform that cleanup as part of
  its own construction.
- **Not pre-loaded with anyone's world.** No default brand, no default UI
  language, no profile named after a line of business (§4.0, G9).
- **Not a billing system.** Spend is measured in weighted tokens. A currency
  figure is produced only when `billing.mode == api`, from a dated and overridable
  price table (§5.1, §7.5).

---

## 3. Architecture

### 3.1 Taller is the program; the chief is its process

**Taller is a standalone program, not a Claude Code plugin.** It runs on its own,
owns its own loop, and delegates every act of inference to the `claude` CLI as a
subprocess (§3.6). Claude Code remains usable on the same project at the same
time, because all shared state is on disk — the two are interchangeable, not
layered.

This is what makes a persistent chief possible. An earlier draft of this design
conceded that Claude Code has no long-running process, so the best available was a
chief that *arrives* briefed each session rather than one that stays briefed.
**That concession no longer applies:** when Taller is the program, Taller is the
process, and the chief lives as long as it does.

Three mechanisms, in descending order of what they now buy:

**A ticket owns a conversation, recorded on disk.** The chief's `session_id` is
captured from its first dispatch and stored in `status.yml` (§7.1); every later
dispatch passes it back as `resume` (§3.6). So the chief's *conversational context*
survives across invocations, stages and days — not merely its briefing. Resuming
ticket 43 tomorrow resumes the conversation about ticket 43.

**There is still no resident daemon.** `taller` is a foreground process that
advances a ticket and exits; nothing runs in the background between invocations,
and `taller cockpit` is a web server, not the chief. Continuity comes from the
stored session id and the files, not from a process that stays alive. §7.6 states
what happens to that session when a ticket goes backwards, and where the
conversation *cannot* follow.

**State on disk, not in the conversation.** The constitution is what the project
*is*; the ticket folder is what is *happening*. Both are files in the repository.
A crash, a compaction, a closed laptop, or a switch to Claude Code mid-ticket lose
nothing. The conversation is not the memory — the repository is. This property was
originally a defence against session death; it is also exactly what lets the two
front ends hand work to each other.

**A briefing that is cheap even so.** Taller injects the chief's routing
instructions and `00-index.md` with `--append-system-prompt` on every call, in
~500 tokens. In a Claude Code session the same content arrives through a
`SessionStart` hook. Either way the chief never has to be told what the project
is.

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

**`00-index.md` is produced mechanically, by `constitution.render_index(ruleset)`.**
It is the whole of the Phase A context goal — the chief parses it, criterion 6
measures it, criterion 7 excludes it — so it needs a named renderer, a writer and a
refresh trigger like any other generated file:

| | |
|---|---|
| **Format** | YAML front matter holding the routing table above, then one line per provided slice |
| **Renderer** | `render_index(ruleset)` — **no model call.** The routing table is derived from the nine-slice vocabulary (§4.3) and `paths`; each slice's one-line summary is the `> ` blockquote that **every module file is required to begin with**, concatenated in profile order. |
| **Writer** | `gitio.commit_to_main()`, as a `main`-side generated file (§7.2) |
| **Refreshed** | On exactly the triggers in §4.6 — `project adopt`, `project new`, every `/taller:amend`, stage ②, and `taller resolve` — so an amendment cannot leave it stale |
| **Conflicts** | `merge=ours`, regenerated not merged, like the other generated files |

**The ≤ 800-token budget of criterion 6 is split explicitly:** `00-index.md` at most
600 tokens, the `CLAUDE.md` stub at most 200. `render_index` counts its own output
and fails rather than silently exceeding the budget the goal is measured on.

### 3.2 Four artifacts, plus runtime state

```
programas/taller/          ① THE PROGRAM — a standalone Python application: the
                              library, the CLI, the cockpit, an inert CATALOGUE
                              of generic stack templates (§4.0), and a thin
                              Claude Code plugin as a second front end (§3.5).
                              No domain-, brand- or language-specific knowledge.

~/.taller/                 ② THE HUB — rules, brands, registry. A git repository.
                              STARTS EMPTY. You fill it (§4.0).

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
| **Inference — the agent loop, tools, subagents, permissions** | **the `claude` CLI, driven as a subprocess (§3.6)** |
| Brainstorm → plan → execute → verify | superpowers (soft dependency, §3.4) |
| Constitution, chief, routing, lanes, gates, tickets, spend, cockpit | Taller |
| Issues, pull requests, CI, branch protection | GitHub via `gh` CLI |

Taller's relationship to `claude` is the same as its relationship to `gh`: it
shells out to a tool the owner already has, authenticated as the owner already
authenticated it. It is not a wrapper around a library and it embeds no model
client.

The GitHub MCP server currently fails authentication (HTTP 401, stale token).
Taller uses the `gh` CLI. `taller setup` verifies its authentication and token
scopes (§4.7). The design has no dependency on any GitHub MCP server.

### 3.4 Dependencies

| Dependency | Kind | Behaviour if absent |
|---|---|---|
| The `claude` CLI, authenticated | **hard** | Every act of inference goes through it (§3.6). `taller doctor` reports it missing or unauthenticated as a failure, not a skip. |

**The `claude` flag surface is pinned, because §3.6.2 argues that this CLI's
defaults move.** `~/.taller/taller.yml` records `cli_min_version`, and `taller
doctor` verifies that every flag §3.6's mapping table depends on —
`-p`, `--output-format json`, `--json-schema`, `--append-system-prompt`, `--resume`,
`--session-id`, `--add-dir`, `--allowedTools`, `--disallowedTools`, `--agents`,
`--model`, `--permission-mode` — is still accepted, and records the observed
version. A mapping table written against an unrecorded CLI is silent breakage
waiting to happen.

**Verified on 2026-09-26 against `claude 2.1.74`:** all twelve required flags
present. Two flags are **optional**, used when present and omitted when not:

| Flag | Status on 2.1.74 | Behaviour without it |
|---|---|---|
| `--permission-prompts none` | absent (needs 2.1.259+) | `--permission-mode dontAsk` carries `unattended` on its own; the only loss is the hint telling Claude not to retry a denied call |
| `--bare` | absent | Nothing to avoid yet. §3.6.2's guard is therefore **forward-looking**, and its `doctor` assertion is what will catch the day it arrives and becomes the default |
| Python 3.11+ | hard | The library, CLI, gate scripts, spend accounting and cockpit are Python |
| `pypdf`, `pillow` | hard for A | Brand extraction from a guide PDF and from a logo image (§4.2) |
| `gh` CLI, authenticated | **hard for A**, D and F | `taller setup` rounds 1 and 3 call `gh auth status` and `gh repo list` (§4.7). Without it, Phase A discovery **degrades to disk-only** and says so; the greenfield path needs no `gh` at all. |
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
| **`taller` CLI** (Python console script) | `setup`, `settings [show\|set\|edit]`, `models probe`, `project new\|adopt\|discover\|brief`, `brand new\|edit`, `ticket new\|show\|list\|transition\|approve\|reject\|resume\|close`, `resolve`, `scan`, `stage`, `doctor`, `cockpit` | Runs outside a session — a terminal, a script, CI, or the deployment host. Reaches inference through `claude` (§3.6). |
| **Slash commands** (in-session) | `/taller:new`, `/taller:approve`, `/taller:reject`, `/taller:resume`, `/taller:amend`, `/taller:status`, `/taller:onboard` | For working inside a conversation the owner is already having, with the owner able to interject at any point. |

**Both front ends can do everything.** The CLI reaches inference through `claude`
as a subprocess (§3.6); the slash commands reach it through the session they are
already in. Neither is a subset of the other in capability — they differ only in
where the conversation lives:

| | `taller` CLI | Slash commands |
|---|---|---|
| Inference | Spawns `claude -p` per step | The current session |
| The chief's context | A per-ticket session id, held by Taller | The owner's own session |
| Needs Claude Code open | **No** | Yes, by definition |
| Runs on a server, in CI, from a script | Yes | No |
| Owner can interject conversationally | Only between steps | At any moment |

Use the CLI when the work should proceed without you watching. Use the session
when you want to be in the conversation. The same ticket can move between them,
because the state is files (§3.1).

**Naming is disjoint.** Project lifecycle is always `taller project …`; ticket
lifecycle is `taller ticket …` on the CLI and `/taller:new` in a session.
`/taller:new` creates a **ticket**; `taller project new` creates a **project**.
No verb means two things. `/taller:reject` exists because a rejection is a
conversational act whose reason must reach `notes.md`.

---

### 3.6 The inference boundary

**One module owns every act of inference: `src/taller/inference.py`.** Nothing
else in Taller spawns `claude`, and nothing else knows how inference is
implemented. The rest of the program asks for a dispatch and receives a result.

```python
Dispatch = {
    "role":      str,            # chief | architect | implementer | fixer |
                                 #   gate_security | gate_quality | gate_ux |
                                 #   explorer | scribe | summariser  (§6)
    "prompt":    str,
    "ruleset":   RuleSet | None, # None during bootstrap — see below
    "config":    HubConfig,      # ALWAYS present; the only source of models/effort
                                 #   when ruleset is None  (§4.4.1)
    "model":     str | None,     # explicit override; wins over role lookup
    "effort":    str | None,     # explicit override
    "system":    str | None,     # explicit briefing when there is no RuleSet
    "resume":    str | None,     # a session_id to continue; None starts fresh
    "cwd":       str,            # a worktree, or the bootstrap scratch dir below
    "writable":  [glob],         # path globs this dispatch may modify
    "forbidden": [glob],         # path globs it may not — §3.6.1
    "tools":     [str],          # the allowlist for this role — §3.6.1
    "agents":    dict | None,    # inline agent definitions, or None — see below
    "schema":    dict | None,    # JSON Schema the answer must satisfy
    "unattended": bool,          # nobody is available to answer a prompt
}

UsageRecord = {
    "model":       str,          # concrete id as reported, never an alias
    "input":       int,          # from input_tokens
    "cache_write": int,          # from cache_creation_input_tokens
    "cache_read":  int,          # from cache_read_input_tokens
    "output":      int,          # from output_tokens
}

Result = {
    "ok": bool, "value": object | None, "error": str | None,
    "session_id": str,           # store it to continue this conversation
    "usage": [UsageRecord],      # per-model usage for THIS dispatch (§7.5)
    "cost_usd": float | None,    # CUMULATIVE when resuming — see §7.5
}
```

`UsageRecord`'s field names are the four that `weights` and `pricing` are keyed by
(§5.1), so the rename from the CLI's `cache_creation_input_tokens` /
`cache_read_input_tokens` happens once, here, on both the `Result` path and the
transcript fallback path.

**Two model namespaces, deliberately, and they never meet.** `model_aliases` maps an
alias to whatever `--model` should be given, which may be a short CLI alias
(`sonnet`) or a full id. `UsageRecord.model` and `pricing` are keyed by the
**concrete id the run reports** (`claude-sonnet-5`), because that is what actually
served the request — a fallback or a silent upgrade would otherwise be invisible.
So `pricing[resolve_model(role)]` is a `KeyError` waiting to happen and is never
correct: cost is always looked up by the reported id, never by the requested one.

**`ruleset` is optional, because the first inference happens before one exists.**
`resolve(path)` reads a project's `.taller/` and its profile, and the primary entry
point runs inference *before either exists*: §11.4 synthesises a constitution from
twelve free-text answers, and §11.1 runs the missing `setup` rounds on an empty hub
where no profile has yet been copied. That is **bootstrap mode**, and it is the
first thing Phase A exercises.

**`config` is always present, which is what makes bootstrap possible.** It is the
hub-only configuration of §4.4.1 — `model_aliases`, `models`, `effort`, `fallback`,
`concurrency`, `billing`, `weights`, `pricing` — loaded without any project. A
bootstrap dispatch resolves `role → config["models"][role] → config["model_aliases"][alias]`
exactly as a project dispatch does through its `RuleSet`. **No caller hardcodes a
model name**, which §5.1 forbids: `model_aliases` remains the only place a concrete
model id appears.

**`cwd` during bootstrap is a scratch directory,** `~/.taller-run/dispatch/scratch/`,
created empty and containing **no `CLAUDE.md` and no `.claude/`**. This matters more
than it looks: §3.6.2 explains that a non-bare dispatch loads the working
directory's `CLAUDE.md` and runs its hooks, so defaulting bootstrap to the process
working directory would silently brief a probe or a wizard turn with whatever
repository the owner happened to be standing in — the opposite of the empty-hub
contract.

**How a gate definition is applied — `--append-system-prompt`, not `--agents`.**
The two are not interchangeable. A gate's answer must land in the top-level
`structured_output` that `schema` depends on, so a gate runs **as the top-level
turn**: its definition becomes `--append-system-prompt` and `schema` becomes
`--json-schema`. `Dispatch.agents` is populated only for a dispatch that needs to
delegate further — in practice the chief — and is `None` for every gate. An earlier
draft implied gates were passed via `--agents`, which would have put their findings
inside a subagent turn where `structured_output` does not reach.

`infer(Dispatch) -> Result` is the whole surface. Its implementation builds a
`claude` invocation:

| `Dispatch` | Becomes |
|---|---|
| `prompt` | stdin, with `-p --output-format json` |
| `model`, else `config`/`ruleset` lookup for `role` | `--model` |
| `effort`, else the `effort` lookup for `role`, else `effort.default` | `--effort <level>` (native flag; verified present on 2.1.74, accepting `low` `medium` `high` `max`) |
| `system`, else the role's slices from `ruleset` | `--append-system-prompt` |
| `resume` | `--resume <session_id>` |
| `cwd` | process working directory |
| `tools` | `--allowedTools` |
| `writable` | `--add-dir` |
| `forbidden` | `--disallowedTools` specifiers — §3.6.1 |
| `schema` | `--json-schema`; the answer arrives in `structured_output` |
| `agents` (chief only; `None` for gates) | `--agents <json>` |
| `unattended: true` | `--permission-mode dontAsk`, plus `--permission-prompts none` when the CLI supports it (§3.4) |

**Session ids are captured, never invented.** `Result.session_id` comes from the
`session_id` field of the JSON result; the caller stores it and passes it back as
`resume` next time. Claude Code resolves a session id from any directory on the
machine, so a ticket's conversation is reachable from its worktree. Taller does not
pre-generate uuids with `--session-id`, because a captured id cannot collide.

### 3.6.0 Which slices brief which role

`Dispatch.system` defaults to "the role's slices from `ruleset`" (§3.6), and nothing
defined which those were — so a UX gate would have been briefed with the security
and product slices as well, which is both wasteful and confusing. §3.1's routing
table answers a different question (what the *chief* loads for a kind of work).

| Role | Slices |
|---|---|
| `chief` | `stack`, `never`, `overrides`, plus whatever §3.1's routing table adds for the work in hand |
| `scribe` | `product` — enough to phrase the ticket in the project's own terms |
| `explorer` | `architecture` — it needs the layers to know where to look |
| `architect` | `product`, `architecture`, `conventions`, `never`, `overrides` |
| `implementer` · `fixer` | `stack`, `architecture`, `conventions`, `brand`, `ux`, `never`, `overrides` |
| `gate_security` | `security`, `never`, `overrides` |
| `gate_quality` | `conventions`, `architecture`, `never`, `overrides` |
| `gate_ux` | `ux`, `brand`, `conventions`, `never`, `overrides` |
| `summariser` | `product` |

`never` and `overrides` reach every role that can change or judge code, for the same
reason §3.1 always loads them: a prohibition or a suppression a dispatch cannot see
has no effect. A slice a project does not provide is simply absent — a missing key,
not an error.

This is also where G1 is actually earned. A gate briefed with three slices instead
of nine is the difference between the design's token claim and a slogan.

### 3.6.1 Tool allowlists, and how `forbidden` renders

**Every role's allowlist is fixed and written down here**, because §15.1 asserts on
the generated argument list and cannot be written against "the specifiers it needs".

| Role | `tools` (→ `--allowedTools`) | `writable` | `forbidden` |
|---|---|---|---|
| `chief` | `Read Glob Grep Bash(git status*) Bash(git log*) Bash(git diff*)` | `[]` | `[]` |
| `explorer` | `Read Glob Grep` | `[]` | `[]` |
| `scribe` | `Read` | `[]` | `[]` |
| `summariser` | `Read` | `[]` | `[]` |
| `gate_security` · `gate_quality` · `gate_ux` | `Read Glob Grep` | `[]` | `[]` |
| `architect` | `Read Glob Grep Write Edit` | the ticket folder only | `[]` |
| `implementer` | `Read Glob Grep Write Edit NotebookEdit Bash` | the worktree | `[]` |
| `fixer` | `Read Glob Grep Write Edit NotebookEdit Bash(pytest*) Bash(python -m pytest*) Bash(git diff*) Bash(git status*)` | the worktree | `paths.tests_dir/**`, `**/test_*.py`, `**/*_test.py` |

Three things this table settles:

**A read-only role needs no `forbidden` list at all.** It is granted no
write-capable tool, so there is nothing to forbid. `forbidden: ["**"]` would be
worse than useless — it is non-empty, so it would trip the `Bash` rule below for a
role that has no `Bash` anyway.

**The implementer keeps unrestricted `Bash` and has an empty `forbidden` list.** It
must be able to run arbitrary commands to build and check its own work. It is
bounded by `--add-dir`, which admits the ticket worktree and nothing else. §9.7's
no-test-file rule applies to the **fixer**, not the implementer: the failure mode
being prevented is "make a failing test pass by editing the test", which is a fix
round's temptation, not a feature's.

**The fixer's `Bash` is allowlisted precisely because its `forbidden` list is
non-empty.** A shell walks straight around a `--disallowedTools` specifier, so the
rule is: **a role with a non-empty `forbidden` list may not have bare `Bash`.** The
fixer gets the specifiers it needs to verify a fix — running the test suite and
reading the diff — and nothing that can write.

`--disallowedTools` takes **permission rule syntax** — tool names and
`Tool(pattern)` specifiers — **not bare paths.** A path passed to it would match no
tool and silently restrict nothing, which would quietly void §9.7's guarantee.
`inference.py` therefore expands each glob in `forbidden` across every
write-capable tool:

```
forbidden: ["tests/**", "**/test_*.py"]
  →  --disallowedTools "Write(tests/**) Edit(tests/**) NotebookEdit(tests/**)
                        Write(**/test_*.py) Edit(**/test_*.py) NotebookEdit(**/test_*.py)"
```

The `main` worktree (§7.3) is **never** in `writable` or `--add-dir` for any
dispatch. `gitio.commit_to_main()` is the only writer of the `main`-side generated
files, and no dispatch should be able to reach them.

### 3.6.2 `--bare` must not be used

`--bare` is documented as the recommended mode for scripted calls and as the future
default for `-p`. **Taller must pass `-p` without it, and must keep working when
the default flips.**

> In bare mode, Claude Code never reads OAuth credentials or the system keychain.

Bare mode therefore **cannot use a subscription** — it requires
`ANTHROPIC_API_KEY`, which is precisely the billing relationship §5.2 exists to
avoid. This is the single largest forward-compatibility risk in the design:
`billing.mode: subscription` silently becomes impossible the day `-p` defaults to
bare and Taller has not opted out. `taller doctor` asserts that a trivial dispatch
succeeds with no `ANTHROPIC_API_KEY` present, which fails loudly if this ever
changes.

Two consequences of *not* using bare mode, both intended: a dispatch loads the
project's `CLAUDE.md` — the stub pointing at `00-index.md`, which is the briefing
Taller wants — and it runs whatever hooks the working directory configures. Since
the working directory is always a Taller-created worktree of the owner's own
project, that is the owner's own configuration.

### 3.6.3 The rest of the contract

**Gate agents need no plugin installed.** `--agents <json>` passes the definitions
inline, so standalone Taller works where the Claude Code plugin was never
installed. The plugin is a convenience for working inside a session, not a
dependency.

**Option B remains a swap, not a rewrite.** Replacing the subprocess with an
embedded Agent SDK client — which would require an API key and forfeit
subscription billing (§5.2) — changes this one module and nothing else.

**The executable is resolved to an absolute path before it is spawned.** On Windows,
`CreateProcess` appends only `.exe` to an extensionless name, so spawning bare
`claude` skips a `claude.cmd` earlier on `PATH` and runs whatever `claude.exe` it
finds instead. Verified on this machine: `shutil.which` returned the shim while
`subprocess.run(["claude", ...])` ran the real binary. Since the test suite
substitutes a stub `claude` on `PATH` (§15.1), resolving first is what keeps the
suite from making real, billed dispatches — and on a subscription those consume the
usage window that §5.2 exists to protect.

**Failure handling.** A non-zero exit, unparseable JSON, a schema mismatch, or a
missing `claude` binary all return `ok: false` with a distinct reason. `infer`
never retries on its own; retry policy belongs to §14 and differs by caller. A
SIGTERM to a dispatch exits 143 with the turn unfinished and no result recorded,
which `infer` reports as an error rather than an empty success.

**`concurrency` is enforced across processes, not within one.** The limit it
protects — a subscription usage window (§5.2) — is per account, while the CLI, the
cockpit and a Claude Code session can all dispatch at once. `inference.py`
therefore takes a slot from a counted semaphore under `~/.taller-run/dispatch/`,
using the same lock mechanism as §10.3, and releases it in a `finally`. A
per-process counter would bound nothing that matters.

**Two pools, not one**, matching §5.1's two keys: `dispatch/slots/thinker/` bounded
by `max_parallel_thinker`, and `dispatch/slots/worker/` bounded by
`max_parallel_gates`. One shared namespace would make an Opus dispatch queue behind
an unrelated Sonnet one and would apply the gate limit to the chief, the
implementer and the scribe as well.

---

## 4. The hub

### 4.0 The hub starts empty; the plugin ships a catalogue

Taller arrives knowing nothing about whoever installs it. There is no default
brand, no default UI language, no profile named after anyone's business, and no
project registered. A freshly installed hub is:

```
~/.taller/
├── taller.yml          mechanical defaults only — models, effort, weights,
│                       thresholds, a universal secrets glob. No language. No brand.
├── projects.json       []
├── brands/             empty
├── modules/            empty
└── profiles/           empty
```

The plugin separately ships a **catalogue** — generic, inert, and copied into the
hub only when something needs it:

```
src/taller/catalogue/          # INSIDE the package
├── modules/
│   ├── stack/flask-sqlite.md      stack/static-site.md      stack/python-packaged.md
│   ├── security/web-app.md        security/minimal.md
│   ├── conventions/python.md      conventions/js.md
│   ├── ux/bootstrap.md
│   └── never.md
├── profiles/
│   ├── flask-sqlite.yml    static-site.yml    python-packaged.yml
└── scaffolds/
    ├── flask-sqlite/       static-site/       python-packaged/     (§11.4)
```

| Property | Why |
|---|---|
| **Named for stacks, never for domains** | `flask-sqlite`, not anyone's line of business |
| **Inert until copied** | Nothing in the catalogue is resolved, loaded or enforced. `taller setup` and `taller project new` copy entries into the hub on demand. |
| **No `brand` and no `language` defaults** | A catalogue profile has `brand: null` and no `language` key. Both are asked, never assumed — a non-English UI is an answer, not the tool's opinion. |
| **Editable once copied** | A copied module is yours. The catalogue is a starting point, not an upstream you track. |

The distinction matters: *empty* means **it knows nothing about you**, not **it can
do nothing**. A first `taller project new` needs a scaffold to create from, and
that is what the catalogue provides.

**A profile copy is atomic with its modules.** Copying `flask-sqlite.yml` into the
hub also copies every module it names, because chain 2 (§4.4) resolves slice text
from `~/.taller/modules/` — a profile whose modules were left in the catalogue
would resolve six dangling references, which §15.1 tests as an error. A module
**already present in the hub is never overwritten**: the catalogue is a starting
point, not an upstream, and a module you have edited is yours. `taller doctor`
reports any profile in the hub naming a module the hub lacks.

**Growth rule.** A catalogue entry enters the hub when a project needs it. A
*new* module — one the catalogue does not contain — is authored only when **two**
projects in that hub need it. This layer is indirection and becomes a maintenance
burden if it grows speculatively.

**Once you have populated it,** a hub looks like this — everything below arrived
by your choice, from the catalogue or from discovery (§4.7):

```
~/.taller/                         git repository — versioned content ONLY
├── taller.yml                     DEFAULT config: models, effort, budget,
│                                  thresholds, language, weights, paths floor
├── projects.json                  registry: path, profile, brand, last seen
├── brands/
│   ├── <your-brand>/
│   │   ├── tokens.css             THE source of truth for colour + font VALUES
│   │   ├── brand.md               which token to use when (names, never values)
│   │   └── assets/                logo, favicon, fonts, images
│   └── <slug>/                    same shape, always
├── modules/                       each file declares the slice it provides
│   ├── stack/flask-sqlite.md          → stack
│   ├── stack/static-site.md           → stack
│   ├── stack/python-packaged.md            → stack
│   ├── security/web-app.md            → security
│   ├── security/minimal.md            → security
│   ├── conventions/python.md          → conventions
│   ├── conventions/js.md              → conventions
│   ├── ux/bootstrap.md                → ux
│   └── never.md                       → never
├── profiles/
│   ├── flask-sqlite.yml    static-site.yml    python-packaged.yml
└── templates/new-project/         stack skeletons

~/.taller-run/                     NOT versioned
├── .lock                          hub write lock (§10.3)
├── registry.lock                  projects.json write lock (§10.3)
├── locks/<project>.lock           per-project write lock (§10.3)
├── onboarding/<name>.yml          wizard scratch (§11.3)
├── smoke/<project>-<id>/          ephemeral smoke data + logs (§9.6)
└── worktrees/<project>-main/      long-lived `main` worktree (§7.3)
```

### 4.1 Profiles

A profile names the modules a project inherits, its default brand, and config
that is stack-specific rather than global.

A profile in the hub is a **copy** of a catalogue entry that you have since
edited — the `brand` and `language` keys below are `null` and absent in the
catalogue, and were filled in by onboarding:

```yaml
# ~/.taller/profiles/flask-sqlite.yml   (as populated; catalogue ships brand: null)
name: flask-sqlite
description: Flask + SQLite WAL + Jinja2 + Bootstrap 5 + Docker + Caddy
modules:
  - stack/flask-sqlite
  - security/web-app
  - conventions/python
  - conventions/js
  - ux/bootstrap
  - never
brand: <your-brand>          # null in the catalogue; set by onboarding
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
# ~/.taller/profiles/static-site.yml
name: static-site
description: Static HTML/JS page with a Python helper script, no server
modules: [stack/static-site, security/minimal, conventions/js, ux/bootstrap, never]
brand: <another-brand>         # a project may have a brand of its own
language: {code: en, ui: es, commits: en}
paths:
  security_sensitive: []       # inherits only the hub floor (§5.1)
  ui: ["*.html", "*.css", "*.js"]
  layers: {}
  tests_dir: "tests"
smoke:
  kind:      http              # served by python -m http.server, not the app
  boot:      "python -m http.server 0 --directory ."
  ready:     "auto"            # port taken from the boot process, §9.6
  timeout_s: 15
  routes:    ["/index.html", "/history.html"]
```

```yaml
# ~/.taller/profiles/python-packaged.yml
name: python-packaged
description: Packaged Python desktop application (PyInstaller)
modules: [stack/python-packaged, security/minimal, conventions/python, never]
brand: none
language: {code: en, ui: none, commits: en}   # a package with no UI
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

`language.ui: none` disables every UI-language rule, so a project with no user
interface is never checked for UI-string language.

The catalogue ships three profiles because three distinct shapes cover most small
estates: a server-rendered web application with a database, a static page with a
helper script, and a packaged program with no UI. A worked mapping of ten real
repositories onto them is in **A.6** — as an illustration, not as a definition.
See §4.0 for the growth rule.

### 4.2 Brands

A brand is a folder. One brand serves many projects; a project has exactly one
brand, or `none`. Colour and font **values** exist only in
`brands/<slug>/tokens.css`. `brand.md` states intent and which token applies
where, by name.

`taller brand new <slug>` is guided and offers three starting points:

| Start from | Mechanism |
|---|---|
| **A brand guide PDF** | The authoritative source when one exists. Preferred over any CSS file, because a CSS file is an implementation that may already have drifted from the guide (A.4 documents an estate with one guide and five disagreeing palettes). Extraction is deterministic: `pypdf` for embedded text, collecting declared colour values (hex, CMYK, Pantone-with-hex) and font names in document order, then ranking a colour by how often it is declared and how early it appears. It **proposes, never decides** — the swatch page is the approval step. A scanned PDF with no text layer yields nothing and says so, rather than guessing from rendered pixels. |
| Existing CSS | Reads `--*` custom properties from a named file and proposes them as the palette. |
| A logo image | Extracts dominant colours from a `logo.png` / `logo.svg` and proposes a palette. |
| Scratch | Guided: primary, accent, semantic (success/warning/danger), surfaces, typography, spacing scale. |

It then collects typography and assets, writes `tokens.css` and `brand.md`, and
renders a **swatch page** (a standalone HTML file opened locally), so a brand is
reviewed visually rather than as a list of hex codes.

### 4.2.1 How the brand reaches the running application

The hub is outside every project repository and outside the Docker image that
gets deployed, so the hub `tokens.css` cannot be the file the browser loads.

**`render_tokens(ruleset)` produces `<project>/<paths.brand_tokens>`** — a profile
key (§7.2), not a fixed path, and unset when `brand` is `none` — a
verbatim copy of the brand's `tokens.css` with a generated-file header — and
`commit_to_main()` writes it as a `main`-side generated file alongside
`resolved.json` (§4.6, §7.2). Same separation as the snapshot: the renderer is
pure, the writer commits. Refreshed on exactly the same triggers, including an
amend to the brand, which fans out to every project using that brand. The
application links it; the Docker image contains it; nothing at runtime depends on
the hub existing.

The constitution gate **exempts that one generated path** and flags colour and
font values anywhere else. Precisely:

| Path | Rule |
|---|---|
| `paths.brand_tokens` (generated) | Exempt — it is the definition |
| Anything else | `brand.hardcoded-color` / `brand.hardcoded-font` |

**What this means at adoption.** A project that already defines its tokens in some
other stylesheet — the common case (A.4) — is not using the generated path, so left
alone every one of those definitions would become a HIGH finding: adoption would
report *more* violations than the project has, by flagging its own design system.
`taller project adopt` therefore:

1. Reads the `:root` block from the stylesheet that defines them — this is exactly
   the `brand new --from-css` path of §4.2 — and lifts those tokens into the hub
   brand.
2. Writes the generated `static/css/tokens.css`.
3. Removes the `:root` block from that stylesheet and adds an `@import` of the
   generated file.
4. Presents all of this in the project brief for approval, like everything else
   (§11.1).

The tokens move; they are not flagged, and the project's real violation count is
unchanged by adoption.

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

Covers `models`, `model_aliases`, `effort`, `fallback`, `billing`, `concurrency`,
`budget`, `weights`, `pricing`, `thresholds`, `language`, `paths`, `smoke`,
`non_suppressible`.
**Nothing in `constitution/` sets configuration.**

**A profile carries both kinds of key, so chain 1 takes only its configuration.**
`name`, `description` and `modules` describe the profile itself or belong to chain
2; `brand` is resolved from the project's registry entry, not from the profile, so a
catalogue profile's `brand: null` must not land in the `RuleSet` and collide with the
resolved brand. Chain 1 excludes all four.

**List merge rule.** Lists **replace** by default, with two exceptions:
`paths.security_sensitive` and `non_suppressible` are **append-only** at every
level. The hub defines a
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
    "model_aliases": {alias: model_id},          # §4.4.1 — needed to map `fallback`
    "models":     {role: alias},                 # an ALIAS, as in HubConfig
    "fallback":   alias,
    "effort":     {role: str},                   # includes a "default" key
    "billing":    {"mode": str},                 # §5.2
    "concurrency":{str: int},                    # §5.2 — enforced in §3.6
    "budget":     {str: int},
    "weights":    {str: float},                  # §7.5
    "pricing":    {"as_of": date,
                   model_id: {str: float}} | None,
    "language":   {"code": str, "ui": str,
                   "commits": str} | None,       # None on an unconfigured hub
    "overrides":  [Override],                    # §4.5
    "non_suppressible": [str],                   # §4.5 — append-only rule ids
    "hub_sha":    str,
    "mode":       str,                           # "local" | "ci"  — §4.6
}
```

`mode` is the one behavioural difference between a local and a CI gate run
(§4.6). `resolve()` sets `"local"`; `load_snapshot()` sets `"ci"`. It travels
inside the `RuleSet` so that `gates/*.py` stay pure over their arguments (§10.2)
rather than reading the environment.

**Determinism:** `resolve()` performs no network access and no model calls. It is
pure over the filesystem, so it is directly unit-testable — which is what makes
the byte-for-byte tamper check in §4.6 possible.

### 4.4.1 `HubConfig` — configuration without a project

`resolve(path)` needs a project. Three callers have none: `taller setup` before
anything is registered, `taller models probe` (which belongs to no project), and
`project new` before its brief is approved. They load the hub layer alone:

```python
HubConfig = {
    "model_aliases": {alias: model_id},
    "models":        {role: alias},
    "effort":        {role: str},          # with a "default" key
    "fallback":      alias,
    "billing":       {"mode": str},
    "concurrency":   {str: int},
    "weights":       {str: float},
    "pricing":       {"as_of": date, model_id: {str: float}} | None,
    "language":      {...} | None,         # None on an unconfigured hub
    "hub_sha":       str,
}
```

`load_hub_config() -> HubConfig` reads `~/.taller/taller.yml` and nothing else. It
succeeds on a completely empty hub, where `language` is `None` and every other key
carries its shipped default.

**`RuleSet["models"]` holds aliases, not model ids** — identically to `HubConfig`,
so one resolver (`role → alias → model`) serves both and `model_aliases` stays the
single place a concrete model name appears (§5.1). An earlier draft annotated it
"aliases already resolved", which would have needed a second resolver and made the
first ruleset-based dispatch fail.

**`RuleSet` embeds a resolved `HubConfig`,** so the two paths differ only in whether
project layers were merged on top. `RuleSet` therefore also carries
`model_aliases` and `fallback` (§4.4) — without them nothing downstream could map
an alias, which would make `models.py`'s fallback responsibility (§10.2) and §14's
"fall back per `fallback:`" unimplementable, since `fallback: worker` is itself an
alias.

**Effort resolution, stated once:** `effort[role]` if present, else
`effort["default"]`. Never a `KeyError` — §5.1's block names six roles explicitly
and `default` covers the other four.

`~/.taller/` is a git repository because one edit can affect six projects.
Amendments have history and can be reverted. `hub_sha` is the hub's `HEAD` at
resolution time and is recorded on every gate verdict (§7.4).

### 4.5 `overrides.md` — format and mechanism

Every rule a gate can report has a **stable id** in one namespace, shared with
`Finding.rule` (§7.4): `<domain>.<rule>`. A **domain** is a subject area, not a
gate — one gate may own several. Ids and their default severities are declared in
§9.7 and are part of each gate's public surface.

| Domain | Owned by |
|---|---|
| `brand` | constitution gate |
| `constitution` | constitution gate |
| `size` | size gate |
| `tests` | tests gate |
| `smoke` | smoke gate |
| `security` | security gate |
| `quality` | code quality gate |
| `ux` | UX gate |

So a hardcoded colour is reported as `gate: constitution, rule:
brand.hardcoded-color`. `Finding.gate` and the rule's domain are independent
fields, which is what lets criterion 14 filter on `brand.hardcoded-*` without
depending on which gate happened to find it.

```markdown
---
overrides:
  - rule:   size.file-too-long
    scope:  "routes/legacy_report.py"     # glob, or "*" for project-wide
    reason: "Being split ticket by ticket; see 0031."
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

**Non-suppressible rules** are, exactly:

1. **Every rule of the security gate** — by domain, so no new security rule is
   suppressible by default.
2. **Every rule id in `non_suppressible`**, a configuration list resolved through
   chain 1 (§4.4) and **append-only**: the hub declares a floor, a profile and a
   project may add to it, and nothing can remove an entry.

```yaml
# ~/.taller/taller.yml, or a project's
non_suppressible:
  - brand.hardcoded-color
  - constitution.layer-violation
```

**Why configuration and not `never.md` front matter.** An earlier draft put this
list in the `never` slice file. Two problems, both found while building the
catalogue:

- It contradicted §4.4's own rule that **nothing in `constitution/` sets
  configuration**. A prose slice is chain 2; a list of rule ids is chain 1.
- Every module file must open with a one-line `> ` summary for `render_index`
  (§3.1), so front matter could not be the first thing in the file — and a parser
  expecting it at line 1 would have read `non_suppressible` as empty and **silently
  made every rule suppressible**. A security-relevant default that fails open
  because of a formatting collision is exactly the kind of defect that survives
  review and surfaces in production.

There is deliberately **no `never.*` rule domain**. The `never` slice is prose, and
prose has no mechanical rules to enumerate. What `non_suppressible` does instead is
name *existing* ids from any domain as un-overridable, which is what "never means
never" actually requires and is decidable. An entry naming an id no gate declares is
reported as `constitution.unknown-rule-id` (MEDIUM).

### 4.6 The resolved snapshot

CI cannot see the hub. The hub is a local-only git repository (§13.2), so a
hosted GitHub runner cannot resolve a `RuleSet`, cannot read the brand
`tokens.css`, cannot know `paths.layers` or `thresholds`, and cannot record
`hub_sha`. Without a fix, the constitution and size gates could not run in CI at
all — which would make §9.4, §13's required check, and §15.7's defence-in-depth
argument false.

**A snapshot of the `RuleSet` is therefore committed to the project repository at
`<project>/.taller/resolved.json`.** It contains the full `RuleSet` with slice
text included, plus the brand's parsed tokens. CI's gates load the snapshot
instead of resolving.

**Five functions, deliberately separated,** so that `resolve()` stays pure
(§4.4) and `constitution.py` never depends on `tickets.py` (§10.2):

| Function | Does | Touches |
|---|---|---|
| `resolve(path) -> RuleSet` | Reads the hub, profile and project. **Pure. Writes nothing.** | reads only |
| `render_snapshot(ruleset) -> bytes` | Serialises a `RuleSet` deterministically | nothing |
| `render_index(ruleset) -> bytes` | Renders `00-index.md` (§3.1) | nothing |
| `render_tokens(ruleset) -> bytes` | Renders the project's `tokens.css` from the brand (§4.2.1) | nothing |
| `gitio.commit_to_main(project, files, msg)` | Writes and commits the bytes to `main` | filesystem, git, network |

Only `commit_to_main()` writes. `taller resolve` is the composition of the five.
Determinism means `render_snapshot(resolve(p))` reproduces the committed bytes
exactly, which is what makes the tamper check below possible **without rewriting
the file it is checking**.

| Property | Consequence |
|---|---|
| Committed and diffable | A pull request shows when the rules governing it changed |
| Self-contained | CI needs no hub, no remote, no secrets, no deploy key |
| Carries `hub_sha` | Verdicts from CI are as traceable as local ones |

**The snapshot always records `mode: "local"`,** whatever the `RuleSet` it was
rendered from held. Otherwise loading a snapshot (which sets `"ci"`) and
re-rendering it would not reproduce the committed bytes, and the tamper check
compares bytes.

**JSON has no date type, and one date is compared rather than displayed.**
`Override.until` is a real `date` in a `RuleSet`, because `overrides.apply` compares
it against today; a string there would raise `TypeError` inside the CI gate, which
is the one place nobody is watching. So `load_snapshot` coerces `until` back to a
`date`, and `pricing.as_of` — which is only ever displayed — is normalised to an ISO
string on the way in so the snapshot stays renderable at all.

**Where it is written and by whom.** The snapshot is a `main`-side generated file,
like the three ticket files (§7.2), and `gitio.commit_to_main()` is the only
writer. It is refreshed:

| When | Scope |
|---|---|
| `taller project adopt` | that project |
| `/taller:amend` or the cockpit Constitution screen | **every project whose profile includes the changed module or brand** |
| stage ② of every ticket | that project, on `main`, before the branch exists |
| any of the above | `resolved.json`, `00-index.md`, and `paths.brand_tokens` when a brand is set — all three are regenerated together, so none can be stale relative to another |
| `taller resolve` | on demand |

An amend to `security/web-app.md` therefore writes to all six `flask-sqlite`
projects: six project locks, six commits, six pushes, six `sync` states. That is
the honest cost of one shared rule and the reason `/taller:amend` reports which
projects it touched. The alternative — refreshing one project — leaves the other
five reporting `constitution.resolved-snapshot-stale` at HIGH until someone
notices.

**Conflicts.** `resolved.json` is generated, so it is never merged.
`.gitattributes` marks it `merge=ours`, and any conflict or divergence is resolved
by discarding both sides and running `resolve()` again. **`ours` is not a built-in
driver** — it does nothing unless `merge.ours.driver` is configured — so `taller
setup` and `project new` both set `git config merge.ours.driver true`, and `doctor`
checks it. Without that, the attribute is decoration and git silently falls back to
a three-way merge of a generated file. A ticket branch never
carries its own snapshot: it inherits `main`'s.

**Line endings are pinned to LF, and this is load-bearing.** The byte-for-byte
comparison below is meaningless if git rewrites the file on the way out of the
index. With `core.autocrlf = true` — the default on Windows — a file committed as
LF is returned as CRLF, so the check would report
`constitution.resolved-snapshot-modified` at BLOCKER on a repository nobody had
touched. Verified during implementation: `b"alpha
beta
"` in the index came back
from the worktree as `b"alpha
beta
"`.

Every repository Taller writes generated files into therefore carries a
`.gitattributes` pinning at least those files to `eol=lf`, and **`project new`
scaffolds one into every project it creates** (§11.4). A renderer that always emits
LF and a VCS that silently rewrites it is a defect that no unit test catches,
because unit tests never round-trip a file through git.

**Tamper check.** CI validates against a file a pull request can edit — a branch
that raised `max_file_lines`, emptied `paths.ui`, deleted the `never` slice text
or appended an override would otherwise get a green CI run against its own
weakened rules, and a hand-edited snapshot keeps the correct `hub_sha`.

**The two checks are ordered, not simultaneous.** Once the hub moves the bytes
necessarily differ, so an unordered pair would raise a BLOCKER on every ticket in
flight during a routine amend — which §14 expects to be a warning at ⑦, not a
block:

| Condition | Verdict | Rule id |
|---|---|---|
| `hub_sha` ≠ hub `HEAD` | **Stale** — checked first. The bytes are *expected* to differ; no tamper conclusion is drawn. | `constitution.resolved-snapshot-stale` (HIGH, `command: taller resolve`) |
| `hub_sha` = hub `HEAD` **and** bytes ≠ `render_snapshot(resolve(path))` | **Modified** — the snapshot cannot legitimately differ from a same-version resolution | `constitution.resolved-snapshot-modified` (BLOCKER, `escalate`) |

The comparison is against an **in-memory** render; nothing is written, so the
check cannot launder the file it is testing.

In CI there is no hub, so neither comparison is possible. CI instead rejects any
diff touching `resolved.json` on a ticket branch — a branch must never carry its
own snapshot (§7.2) — reporting `constitution.resolved-snapshot-modified`
(BLOCKER). CI cannot verify the snapshot's *content*, but it can verify that the
branch did not change it — which is sufficient, because the local ordered check
runs at stage ② before any pull request exists and its verdict is committed with
the work.

### 4.7 `taller setup` — how projects and brands are found

A hub starts empty (§4.0), and registering ten projects by hand is something
nobody does twice. `taller setup` populates it by discovery. It is re-runnable and
writes nothing before its final approval.

| Round | Does |
|---|---|
| **1 · Connect** | Runs `gh auth status`; reports the account and token scopes, and prints the exact `gh auth refresh -s <scope>` command if `repo` or `workflow` is missing. Asks for the deployment host (§13.1) if there is one. |
| **2 · Locate** | Asks for one or more **project roots** on disk. Proposes the parent directory of the current repository as a starting guess. |
| **3 · Discover projects** | Walks the roots for `.git` directories; lists remote repositories with `gh repo list`; matches the two by remote URL. |
| **4 · Discover brands** | Clusters design tokens and locates brand guides across the projects chosen in round 3. |
| **5 · Language & conventions** | Asks for `language` — code, UI and commit-message languages. **No default.** |
| **6 · Review** | Everything it is about to write: projects to register with a guessed profile each, brands to create, catalogue entries to copy. Approve / edit / cancel. |

**Round 3 sorts what it finds into four buckets,** each with a different offer:

| Bucket | Offer |
|---|---|
| Local **and** remote | Register. A stack guess is shown for correction. |
| Local, **no remote** | Register, and offer to create a private remote. |
| **Remote, not cloned** | List it. Offer to clone — **default no**, since a listed repository is not necessarily wanted. |
| Local, remote **does not resolve** | Flag it. A renamed or deleted repository leaves a stale `origin`, which is worth knowing before Taller starts pushing to it. |

**Round 4 turns brand creation into brand confirmation.** For every project being
registered it:

1. Extracts `--*` custom properties from CSS and clusters projects by palette.
2. Locates candidate brand assets — `logo.*`, `favicon.*`, and **brand guide PDFs**.
3. Reports the clusters and proposes a brand per cluster, for naming.

So the question is never "invent a brand" but *"these projects share an identical
set of tokens, and this PDF looks authoritative — what is this brand called?"* A.4
documents an estate where this found one brand guide, five disagreeing palettes
across six projects of the same business, and one project with no tokens at all —
none of which would have surfaced from a blank `brand new` prompt.

**Pickers, not typed slugs.** Wherever the spec says a profile or brand is chosen
— §11.1 steps ⑨ and ⑩, `brand edit`, the cockpit — it is a numbered list of what
the hub holds, **plus what the catalogue offers** (§4.0), plus `create new…` and,
for brands, `none`. The catalogue entries matter most on a genuinely empty hub,
which is Phase A's own pilot: a picker listing only the hub would offer nothing. Never a free-text field whose
value has to be spelled correctly to match a directory name.

**Keeping it fresh.** `taller project discover` re-runs rounds 3 and 4 and reports
what is new, moved, or gone. `taller doctor` already fails on a registered path
that no longer exists (§15.4).

---

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
with an empty list — the target state for any two projects sharing a profile.

### 5.1 taller.yml

```yaml
# ~/.taller/taller.yml — defaults for every project
model_aliases:                # the ONLY place a concrete model name appears
  thinker:  opus
  worker:   sonnet
  cheap:    haiku
  creative: fable             # untested; unassigned by decision

models:                       # role -> alias. Ten roles, matching §6.
  chief:         worker        # CLI only; ignored inside a Claude Code session (§6.1)
  architect:     thinker
  implementer:   worker
  fixer:         worker
  gate_security: thinker
  gate_quality:  worker
  gate_ux:       worker
  explorer:      cheap
  scribe:        cheap
  summariser:    cheap

effort:                       # role key if present, else `default` (§4.4.1)
  chief:         low          # routing is low-judgement work
  architect:     high
  implementer:   medium       # named explicitly: code-writing must not be `low`
  fixer:         medium
  gate_security: medium
  gate_quality:  medium
  gate_ux:       medium
  default:       low          # explorer, scribe, summariser

fallback: worker              # unreachable model degrades, never crashes

cli_min_version: "2.1.74"     # §3.4 — verified 2026-09-26; `doctor` checks the flags

language: null                # NO DEFAULT. Asked at `taller setup`, round 5.
                              # e.g. {code: en, ui: es, commits: en}

paths:
  security_sensitive:         # GLOBAL FLOOR — profiles and projects append (§4.4)
    - ".env*"                 # universal; nothing here assumes a stack or a domain
    - "**/*secret*"
    - "**/*credential*"

billing:                      # detected by `taller setup`; overridable (§5.2)
  mode: subscription          # subscription | api | bedrock | vertex

concurrency:                  # matters most on `subscription` (§5.2)
  max_parallel_gates:   3
  max_parallel_thinker: 1

weights:                      # relative cost weights, tunable (§7.5)
  input:        1.0
  cache_write:  1.25          # standard Anthropic ratio
  cache_read:   0.1           # standard ratio; some models are cheaper still
  output:       5.0           # holds across every model in the roster

pricing:                      # per million tokens. Used only when billing.mode == api
  as_of: 2026-06-24           # `doctor` warns when this is stale
  claude-opus-5:   {input: 5.00,  output: 25.00}
  claude-sonnet-5: {input: 2.00,  output: 10.00}
  claude-haiku-4-5: {input: 1.00, output:  5.00}
  claude-fable-5-1: {input: 10.00, output: 50.00}

budget:                       # compared against spend.weighted_tokens (§7.5)
  per_ticket_warn:  400000    # ≈3× the worked fast-lane ticket in §7.1 (130,350)
  per_ticket_stop: 1200000    # ≈9× — a full-lane ticket with an Opus plan
                              #   and an Opus security gate should fit under this

thresholds:
  max_file_lines:       800
  max_function_lines:    80
  max_fast_lane_lines:   50
  max_fix_rounds:         2
  min_coverage_pct:       0   # 0 = report only, never fail
  dup_block_lines:       12
```

```yaml
# <project>/.taller/taller.yml — e.g. a project stricter about file size
thresholds:
  max_file_lines: 400
paths:
  security_sensitive:          # APPEND-ONLY (§4.4)
    - "billing/**"
```

A new model release is **one line in `model_aliases`**, not one edit per agent
file. `fallback` means a model name the account cannot reach degrades to `worker`
rather than failing mid-ticket.

### 5.2 Settings — one surface, and how Claude is reached

Configuration is resolved from three files (§4.4, chain 1) but must be *read and
changed* from one place. `taller settings` is that place:

| Command | Does |
|---|---|
| `taller settings` | Prints every effective key, its value, and **which layer it came from** — hub, profile or project |
| `taller settings set <key> <value>` | Writes to the right layer: a project key to the project file, a shared key to the hub, under the appropriate lock (§10.3) |
| `taller settings edit` | Opens the relevant file in `$EDITOR` |

The cockpit renders the same list as a Settings screen (§12). Both call the same
library, so a value changed in either place is the same value.

**Taller holds no credentials of its own.** Every act of inference is performed by
the `claude` CLI (§3.6), authenticated as the owner already authenticated it.
Taller never stores an API key and never reads the *value* of one — it checks only
whether the auth-selecting variables are set, in order to report `billing.mode`
below. It never authenticates to Anthropic itself.

**`billing.mode` is detected, not asked,** because it is determinable:

| Detected from | `mode` |
|---|---|
| `CLAUDE_CODE_USE_BEDROCK` set | `bedrock` |
| `CLAUDE_CODE_USE_VERTEX` set | `vertex` |
| `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` set | `api` |
| none of the above | `subscription` |

It is shown at `taller setup` for confirmation and can be overridden. It matters
because **the two modes are constrained by different things**:

| | `subscription` | `api` |
|---|---|---|
| What you pay | A flat fee | Per token |
| The binding limit | **A usage window.** Exhausting it stops work regardless of how cheap the tokens were | Money |
| `spend.cost` | `null` — a dollar figure would be fiction | Computed from `pricing` |
| `weighted_tokens` | A **pacing** signal: how hard this ticket leaned on the window | A proxy for cost |
| What to tune | `concurrency` | `models`, `effort`, `budget` |

`concurrency` exists for the subscription case specifically. Five gates dispatched
in parallel, one of them on the `thinker` alias, can consume a usage window in
minutes — and unlike an API bill, that failure is not gradual: work simply stops.
`max_parallel_gates: 3` and `max_parallel_thinker: 1` bound it. On `api` the same
keys are a latency and rate-limit control rather than a hard constraint.

`pricing` ships with an `as_of` date and is only consulted when
`billing.mode == api`. `taller doctor` reports it as stale past 90 days rather
than silently computing yesterday's cost — a price table is the one part of this
configuration that goes wrong without anything changing locally.

---

## 6. Model roster

Ten roles. The nine specialists each have an agent definition in `agents/`
(§10.1); the chief has none, because it is the orchestrator rather than a
dispatched agent. Four gates have no agent at all.

| Role | Alias | Rationale |
|---|---|---|
| **Chief** | `worker` | Classifies, picks the lane, selects gates, dispatches. Routing is low-judgement work. CLI only — see §6.1. |
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

### 6.1 The chief's model, in each front end

The chief is a role like any other in the CLI, and not configurable at all in a
session. Both cases are real, so `models:` carries a `chief` key and §6's table
lists it:

| Front end | The chief's model |
|---|---|
| **`taller` CLI** | `models.chief`, resolved and passed as `--model` like every other role (§3.6). Default `worker` — routing is low-judgement work. |
| **Claude Code session** | Whatever the owner selected. Taller cannot set the model of a session it is running inside, so `models.chief` is ignored there. |

In the session case only, `/taller:new` reads the session model from the transcript
(§7.5) and warns on a mismatch:

| Situation | Warning |
|---|---|
| Session on `thinker`, ticket triaged `fast` | "This ticket is a fast-lane fix; your session is on Opus. Consider Sonnet." |
| Session on `cheap`, ticket triaged `full` with a design stage | "This ticket needs a plan; your session is on Haiku. Consider Opus." |

A warning only. It never switches models and never blocks. The warning has no
meaning in the CLI, where Taller chose the model itself, and is not emitted there.

### 6.2 Model availability

The set of available models cannot be enumerated from Claude Code (`--model`
accepts an alias or a full name and does not list options).

`taller models probe` issues one trivial `infer()` dispatch per candidate
(`opus`, `sonnet`, `haiku`, `fable`, plus any name the owner adds), using
`Dispatch.model` to name the candidate and `ruleset: None` because a probe belongs
to no project (§3.6). It records which returned, with latency, into
`~/.taller/models-probe.json`. `models.load_probe()` reads that file; the gates and
`doctor` never probe on their own.

It works from the CLI because inference goes through `claude` (§3.6), which is
authenticated. Taller needs no key of its own for this, or for anything else.

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
title: Mismatch warning uses a different red from the rest of the app
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
blocked: null              # null, or {reason, at_stage, since} — §8.4
fix_rounds: 1
chief_session: 9f2c1b74-0a3e-4d51-8b6c-2e7f4a1d905c   # §7.6; null before ②
sync: ok                   # ok | local | pending — remote mirror state (§7.3)
templates:                 # written at ②; drives the smoke gate (§9.6)
  templates/dia.html: ["/dia", "/dia/<fecha>"]
checkpoints:               # pending | approved | rejected | skipped
  design:  skipped         # not in the fast lane
  review:  pending
  staging: skipped         # not in the fast lane
  release: pending
spend:
  partial: false
  by_model:
    claude-haiku-4-5: {input: 1200, cache_write: 9000, cache_read: 31000, output: 3100}
    claude-sonnet-5:           {input: 2400, cache_write: 22000, cache_read: 64000, output: 12600}
  total_tokens:    145300   # raw sum, for reference only
  weighted_tokens: 130350   # §7.5 — this is what budget compares against
  cost: null                # populated only when `pricing` is configured
```

Worked through, so the arithmetic can be checked against §7.5's formula and
§5.1's weights:

```
haiku    1,200×1.0 +  9,000×1.25 + 31,000×0.1 +  3,100×5.0 =  31,050
sonnet   2,400×1.0 + 22,000×1.25 + 64,000×0.1 + 12,600×5.0 =  99,300
                                                    weighted = 130,350
```

Output is 78,500 of 130,350 — 60% — while being only 11% of the raw token count.
That is the weighting doing its job, and it is why `per_ticket_warn` is
calibrated against this figure rather than against 145,300 (§5.1).

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
| `.taller/resolved.json` | **`main`** | adopt, amend, ② | Generated; a branch must never carry its own (§4.6) |
| `.taller/constitution/00-index.md` | **`main`** | adopt, amend, ② | Generated by `render_index()` (§3.1) |
| `.gitattributes` | **`main`** | adopt, `project new` | Pins generated files to `eol=lf` and `merge=ours`. Without it the tamper check fires on a clean checkout (§4.6). |
| `paths.brand_tokens` | **`main`** | adopt, brand amend | Generated from the hub brand (§4.2.1). **Absent when `brand` is `none`.** |
| `plan.md` | branch | ③ | Belongs to the work; merges with the PR |
| `gates/*.md` | branch | ⑤, ⑥ | Belongs to the work; merges with the PR |

The three generated files are `main`-side for the same reason as the ticket files,
and `gitio.commit_to_main()` is the only writer of any of them. They are marked
`merge=ours` in `.gitattributes` and regenerated rather than merged (§4.6), so
§7.3's rebase-safety argument holds: none can conflict with application code.

**The brand token path is a profile key, not a constant.** `paths.brand_tokens` is
`static/css/tokens.css` for `flask-sqlite`, `tokens.css` for `static-site` (whose
assets sit at the repository root), and **unset** for `python-packaged`, which has
`brand: none`. A hardcoded path would have missed for two of the three shipped
profiles, including the gate exemption in §9.1.

**On rejection at ⑦** the gate verdict files and the owner's reason are copied to
`main` under `work/NNNN-slug/rejected/<timestamp>/` **before** the worktree and
branch are deleted.

### 7.3 Writing to `main` while the work is on a branch

Roughly a dozen times per ticket, making it the most frequent write in the
system. Taller maintains a **long-lived worktree of `main`** at
`~/.taller-run/worktrees/<project>-main/`, created at `taller project adopt`.
It is outside the project tree and outside the hub repository, so it never
interferes with the owner's running application, the ticket worktree, or a live
database's write-ahead log.

**Creating the worktree needs `--force`, and that has a consequence.** Git refuses a
second checkout of a branch that is already checked out — and at `project adopt`, and
at the end of `project new`, the project's own checkout **is** on `main`. So
`ensure_main_worktree()` passes `--force`, after which the two worktrees share one
branch ref.

**Therefore every `commit_to_main()` opens with `git reset --hard`.** Without it,
Taller silently deletes the owner's work. Verified:

```
owner commits owners_file.txt in their own checkout, on main
  → the shared Taller worktree's index reports:  D  owners_file.txt
```

That is a **staged deletion of the owner's file**, and the next `commit_to_main()`
would carry it to `main`. The reset is not hygiene; it is the thing standing between
this design and data loss.

One unavoidable side effect, worth stating so nobody treats it as a bug: while the
owner's own checkout is on `main`, a `commit_to_main()` leaves their `git status`
showing Taller's files as deleted. Nothing can be done about it without touching
their checkout, which this section forbids. It does not arise in the normal ticket
flow, where the owner is on a branch.

**`ensure_main_worktree()` requires a branch literally named `main`** and fails
clearly otherwise — so `project new` must `git init -b main` rather than rely on a
machine's `init.defaultBranch`.

`gitio.commit_to_main(project, files, message)`:

1. Take the project lock (§10.3).
2. **If `origin` exists:** `git -C <wt> fetch && git -C <wt> merge --ff-only origin/main`.
3. Write the files atomically; commit.
4. **If `origin` exists:** `git -C <wt> push`.

**No-remote mode is the greenfield default, not an error path.** §11.4 ends
`project new` with `git init`, one commit, and a remote *only if asked*; §13.2 makes
local-only the default for the hub too. `git fetch origin` and `git push` both exit
128 with no remote configured (a bare `git fetch` is merely a no-op, so the check is
for a configured remote rather than for a failing fetch). Without this branch Phase
A's own pilot — the thing criterion 2
measures — would either crash or sit permanently in `sync: pending`, which `doctor`
reports as a failure. `sync` therefore has three values:

| `sync` | Meaning |
|---|---|
| `ok` | A remote exists and the local commit is pushed |
| `local` | **No remote is configured.** Nothing to sync; not a fault. `doctor` passes. |
| `pending` | A remote exists but the push has not landed. `doctor` reports it. |

**Ordering constraint.** `ensure_main_worktree()` cannot create a worktree in a
repository with no commits, so on the greenfield path it runs **after** `project
new`'s initial commit, not before it. `project adopt` has commits already and is
unaffected.

**Local state is the truth; the remote is a mirror.** Every failure degrades to
`sync: pending` rather than losing a transition:

| Failure | Behaviour |
|---|---|
| Fast-forward merge refused (owner committed on `main`, or the remote moved) | **Rebase** the `main`-side paths (§7.2) onto `origin/main` and retry once. All but one are under `.taller/`, so they cannot conflict with application code. `paths.brand_tokens` sits inside the application's own tree, so a brand amend can collide with a branch that also touched it — it is generated, so the conflict is resolved by **discarding both sides and re-running `render_tokens()`**, exactly as for `resolved.json` (§4.6). No generated file is ever merged. |
| Rebase also fails, or the push is rejected | Commit stays local and `commit_to_main` **returns** `pending`; its caller records that in `status.yml`, since gitio does not parse a file it was handed. The cockpit shows the ticket as unsynced with the reason. Work continues. |
| A rebase conflict in a path this call is **not** writing | Abort the rebase and degrade to `pending`. Conflicts are auto-resolved **only** where every conflicted path is a generated file this call is about to overwrite; resolving the owner's application code on their behalf is not gitio's decision to make. |
| `sync: pending` present at the next `commit_to_main` | Retry the push first. `taller doctor` reports any ticket left `pending`, and ignores `local`. |

Commit-and-push is not atomic, and §10.3's atomic replace covers files only —
hence `sync` as an explicit, visible state rather than an assumed invariant.

`main` requires a pull request, with the owner's admin bypass retained and used
**only** by this function, for the `main`-side paths of §7.2 — nothing else, ever.

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

**`Result.usage` is the authoritative source, and `status.yml` is the store.**
Every dispatch goes through `infer()` (§3.6), which returns `[UsageRecord]` for
that dispatch, so attribution needs no heuristic. `spend.fold(ticket, result)`
merges those records into `status.yml`'s `spend.by_model` block **at dispatch
completion, under the project lock** — the rollup *is* the store, so there is no
separate usage log and no file for the records to be lost from. `for_ticket(t)`
then simply reads what has accumulated.

This is why `spend.py` depends on `tickets` and `locking`, not only on transcript
files: a module that could see only transcripts could never reach the authoritative
path, and every ticket would silently fall back to parsing.

**One trap, stated because it would silently double-count.** `cost_usd` from a
**resumed** session reports the *whole conversation's* cumulative total, earlier
runs included — and the chief's session is resumed at every stage (§7.6). Summing
`cost_usd` across a ticket's dispatches would therefore multiply the chief's spend
by the number of stages. `spend.py` accumulates **per-dispatch `usage`** and treats
`cost_usd` as a cross-check on the final dispatch only. Both figures are
client-side estimates in any case.

**The transcript is the fallback, for work Taller did not dispatch.** A ticket
advanced inside a Claude Code session spends tokens that no `Result` describes.
There, `spend.py` parses `~/.claude/projects/<slug>/<session>.jsonl`, whose
assistant records carry `message.model` and a full `message.usage`
(`input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`,
`output_tokens`) plus `timestamp`, `gitBranch`, `agentName` and `isSidechain` —
verified against a live transcript. Attribution there is by `gitBranch`, with a
stage-transition time window for records predating the branch.

Note that the `<slug>` differs between the two paths, because a dispatch's `cwd` is
the ticket worktree rather than the project checkout. `spend.py` resolves the slug
from the path it is asked about rather than assuming one.

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

**`spend.cost` is computed only when `billing.mode == api`** (§5.2). On any other
mode it stays `null` regardless of whether a `pricing` table is present, because a
dollar figure for a flat-fee subscription would be fiction. The cockpit hides cost
entirely in that case.

A dated `pricing` table **is** shipped (§5.1) and is overridable. It carries
`as_of` and `taller doctor` reports it stale past 90 days, because a price table is
the one part of this configuration that goes wrong while nothing changes locally.
Shipping a dated table is more useful than shipping none, provided it is honest
about its age.

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

### 7.6 The chief's session: scope and lifecycle

**Only the chief holds a session.** Every specialist dispatch — architect,
implementer, fixer, the three LLM gates, explorer, scribe, summariser — is
**one-shot**, with `resume: None`. They receive a prompt and return an answer;
their output persists as `plan.md`, a diff, or a verdict file, so a conversation
would add cost without adding memory. One id per ticket, stored as
`chief_session`, and no ambiguity about whether a session is per role or per model.

| Transition | The session |
|---|---|
| ① intake → ② triage | Created at the first chief dispatch; `session_id` captured and stored |
| ② → ③ → ④ → ⑤ → ⑥ → ⑦ forward | **Kept.** This is the continuity the design is for. |
| **Promotion to `full` at ④** (§8.2) | **Kept.** The chief is mid-ticket, the diff is retained, and the architect it now dispatches is one-shot anyway. |
| **Rejection at ⑦** → back to ② | **Abandoned.** `chief_session` is set to `null` and a fresh conversation starts. A conversation holding a rejected plan and code that no longer exists is worse than a clean start, and the owner's reason is in `notes.md` (§7.2), which briefs the new session. |
| `blocked` set, then resumed (§8.4) | Kept. Nothing was thrown away. |
| ⑫ close | Retained in `status.yml` for the record; never resumed. |

**Where the conversation cannot follow.** `/taller:resume` inside a Claude Code
session runs in *that* session, not the ticket's. The ticket's conversation is not
reachable from the second front end.

This is a real limit and the earlier text overstated it. To be precise about what
§3.5's "the same ticket can move between them" means:

| | Moves between front ends |
|---|---|
| `ticket.md`, `status.yml`, `notes.md`, `plan.md`, gate verdicts, the branch, the worktree | **Yes** — all on disk |
| The chief's conversation | **No** — it belongs to whichever front end created it |

A ticket picked up in a Claude Code session is therefore briefed from disk — the
original "arrives briefed" mechanism (§3.1), still intact as the fallback it always
was. Nothing is lost that was written down; what is lost is the unwritten part of a
conversation, which is exactly why `notes.md` records decisions and their reasons
rather than only outcomes.

**Concurrent drive of one session is prevented.** Resuming the same `session_id`
from two processes at once would interleave two conversations. The project lock
(§10.3) is therefore taken for the duration of a chief dispatch, not only around
file writes — so the CLI and the cockpit cannot advance the same ticket
simultaneously, and the loser fails with a clear message after 5s.

---

## 8. Lifecycle

### 8.1 Twelve stages

| # | Stage | What happens |
|---|---|---|
| ① | intake | Owner describes it in any words. Chief classifies. Ticket committed to `main`, `gh issue` opened. |
| ② | triage | Slices loaded, snapshot refreshed. Explorer locates files. **Lane decided.** |
| ③ | design | Architect writes `plan.md`. **Owner checkpoint 1.** |
| ④ | build | Worktree + branch. Implementer writes code and commits. |
| ⑤ | gates | Selected gates in parallel, up to `concurrency.max_parallel_gates` (§5.2, enforced in §3.6). Findings → fixer, max `max_fix_rounds`. |
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
A token-replacement ticket is a template or stylesheet edit `pytest` would not
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
or **touches any path matching `paths.security_sensitive`**. `lane: full` is written
to `status.yml`, `checkpoints.design` is rewritten from `skipped` to `pending`, the
owner is told, and the ticket re-enters ③. **The existing diff is kept** and handed
to the architect as input; `plan.md` documents what was already written. The chief's
session is **kept** (§7.6). A ticket is never demoted from `full` to `fast`.

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
`alt` attribute) when `language.ui` is set and not `none`. It does not judge the language —
that is not decidable — it simply puts the new string in front of the owner at
⑦. Single-language UI is therefore *reviewed* but not *enforced* in the fast lane,
and that is a deliberate trade, not an oversight.

### 8.3 Git conventions

| Rule | Form |
|---|---|
| Branch | `ticket/NNNN-slug`, always. Created by the chief; the owner never types it. |
| Commit | `type(scope): summary` — types `feat` `fix` `refactor` `chore` `docs` `test` `perf`. Shape checked mechanically. |
| Scope | One ticket, one branch, one pull request. |
| `main` | Always deployable. |

One convention replaces whatever mix an adopted repository arrived with — A.6
records an estate using `feat/` and `feature/` interchangeably.

**Note on long-lived branches.** An adopted repository may arrive with a divergent
long-lived branch. Such branches drift until merging them becomes its own project.
Under Taller it becomes a series of tickets merged individually. An observation;
out of scope (§18).

### 8.4 `blocked` is a flag, not a stage

There are exactly twelve stages and `blocked` is none of them. A ticket that stops
**keeps its stage** and sets an orthogonal field:

```yaml
blocked:
  reason:    "constitution gate: brand.hardcoded-color survived 2 fix rounds"
  at_stage:  5
  since:     2026-09-26T11:02:00
```

Written this way for four reasons: §14's own wording is "blocks at its current
stage"; `/taller:resume` needs to know which stage to resume *to*; §12's Board
renders columns by stage ① → ⑫, so a ticket whose stage was overwritten with
`blocked` would appear in no column at all; and §15.4's "every `status.yml` parses"
cannot be asserted against a twelve-value enum that sometimes holds a thirteenth
value. The Board shows a blocked ticket in its own column with a marker.

Clearing `blocked` is what `/taller:resume` does, along with whatever the reason
required.

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
Identifying which language a string is written in is a heuristic, so that rule
lives in the UX gate. A gate that sometimes needed a model could not honour §9.4's promise of
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

Severity decides **whether** something is acted on; `remediation` (§9.7) decides
**who** acts.

| Severity | Action |
|---|---|
| `BLOCKER`, `HIGH` | Acted on per the rule's `remediation`: `agent` dispatches the fixer for up to `max_fix_rounds` (2); `command` runs a deterministic command; `escalate` stops and asks the owner with no automatic attempt |
| `MEDIUM` | Reported in the owner's summary. Never auto-fixed. |
| `LOW`, `NIT` | Logged in the ticket. No action unless the owner asks. |

Applies identically to ⑤ gate findings and the ⑥ smoke gate. The 2-round cap is
the cost control: without it, 12 findings spawn 12 fixes which re-trigger the
gates, recursively. **No fix round may modify a test file** (§9.7).

### 9.4 CI is a backstop, not a second opinion

`.github/workflows/taller-ci.yml` runs **only the three model-free gates** —
constitution, size, `pytest` — loading `.taller/resolved.json` (§4.6) rather than
resolving. No hub, no secrets, no API key, no per-push LLM cost, under a minute.
It replaces `code-review.yml`, `security.yml` and `design-review.yml`.

**The job always runs**, and must not use a workflow-level `paths-ignore`: on
GitHub a required check that never reports leaves the pull request pending
forever, making §13's "require `taller-ci` green" a merge deadlock.

**Two jobs in one workflow**, because one job emits exactly one check run:

| Job | Check name | Behaviour |
|---|---|---|
| `gates` | `taller-ci` — **the required check** | Classifies the push. Ticket-file-only → exit 0 immediately. Otherwise run the three model-free gates. Always reports a conclusion. |
| `mode` | `taller-ci-mode` — informational, not required | Reports `full` or `ticket-files` for the same push. |

The required check always reports, so the pull request never deadlocks. The
informational check is what lets `taller doctor` (§15.4) distinguish a real green
from an early exit — without it the newest run on `main` is almost always a
ticket-file commit, and "CI is green" would be vacuous.

### 9.5 Repository scan mode

Each Python gate **except smoke** exposes `scan(tree, ruleset) -> [Finding]`
alongside `run(diff, ruleset)` — the same rules applied to the whole working tree
instead of a diff. Smoke has no tree-wide meaning and is exempt. `taller scan`
drives it, produces the cockpit Health figures (§12), and quantifies a project's
pre-existing violations at adoption. Phase C.

### 9.6 The smoke gate

The fast lane's safety argument rests on ⑥, so it is specified, not left to the
implementer. Configuration comes from `smoke` in the profile or project
`taller.yml` (§4.1) and is reachable as `RuleSet["smoke"]`.

| `kind` | Behaviour |
|---|---|
| `http` | Run `boot` as a subprocess in the isolated environment below. Poll `ready` until HTTP 200 or `timeout_s`. GET every URL in `routes`, plus every **mapped route** (below). Terminate the subprocess in a `finally`. |
| `import` | Import `module` in a subprocess with `timeout_s`. Any exception is a finding. |
| `none` | Gate reports `result: pass` with `metrics: {skipped: true}`. Declared explicitly, never inferred. |

**A 200 is required, not a 3xx.** An application with a login redirects an
unauthenticated request to a login page and returns 302 — which would pass a
naive check while rendering nothing. Since §8.2's whole fast-lane argument is
"⑥ is the only step that renders a template", the gate requires **HTTP 200 with a
non-empty body** on every route, and reports `smoke.not-rendered` (HIGH) on a 3xx
to an unauthenticated location. Redirects are followed only when `auth` is
configured and the final response is 200.

**Environment isolation.** The gate never touches live data, a live port, or
another ticket's run:

```yaml
smoke:
  kind:      http
  boot:      "python run_local.py --port $TALLER_SMOKE_PORT"
  ready:     "http://127.0.0.1:$TALLER_SMOKE_PORT/"
  timeout_s: 30
  routes:    ["/"]
  data:      copy              # copy | fresh | none
  env:
    FLASK_ENV: testing
    DATABASE_PATH: "$TALLER_SMOKE_DATA/app.db"
  auth:
    kind:    basic             # none | basic | form
    user:    "smoke"
    secret:  "$TALLER_SMOKE_SECRET"   # from the environment, never in the file
```

| Key | Rule |
|---|---|
| `$TALLER_SMOKE_PORT` | **Allocated by the gate** — an ephemeral free port, injected into `boot`, `ready` and `env`. Never a fixed port, so a smoke run cannot collide with the owner's own dev server or with a second ticket's run. `ready: "auto"` means "use the allocated port at `/`". |
| `data: copy` | A **copy** of the project database into a temporary `$TALLER_SMOKE_DATA`, discarded afterwards. `fresh` runs migrations on an empty file; `none` means the app needs no database. **The live database and its `-wal`/`-shm` files are never opened** — the same care §13.1 takes for staging, and the reason §7.3 keeps worktrees away from them. |
| `env` | Merged over the subprocess environment, after `$TALLER_SMOKE_*` substitution. |
| `auth` | How to reach an authenticated page. Secrets come from the environment; `taller doctor` reports an unset one rather than the gate failing mysteriously. |

Rule ids: `smoke.boot-failed` (BLOCKER), `smoke.route-error` (BLOCKER),
`smoke.not-rendered` (HIGH), `smoke.timeout` (HIGH),
`smoke.unmapped-template` (MEDIUM).

**Mapped routes** — how "the change is exercised" becomes decidable. At ② the
explorer writes a `template → routes` map for the changed templates into
`status.yml`, derived from `render_template(...)` call sites. The smoke gate GETs
those routes. When a changed template cannot be mapped to any route (an
`{% include %}` partial, or a dynamic name), the gate reports
`smoke.unmapped-template` at `MEDIUM` and falls back to `routes` — so an
unverifiable template is *visible to the owner at ⑦* rather than silently
unchecked. The map is written to `status.yml` as `templates:` (§7.1).

### 9.7 Rule ids and default severities

Three mechanisms key off severity — the fixer, the summary, and §4.5's
downgrade — so severity belongs to the rule id, not to the implementer's
judgement. Severity alone is not enough, though: **not every blocker should be
handed to an LLM.** A `remediation` column decides who acts.

| `remediation` | Meaning |
|---|---|
| `agent` | Dispatch the fixer (`worker`), up to `max_fix_rounds` |
| `command` | Run the named deterministic command; never an LLM |
| `escalate` | Stop and ask the owner. No automatic attempt. |

| Rule id | Severity | Remediation |
|---|---|---|
| `brand.hardcoded-color` | HIGH | `agent` |
| `brand.hardcoded-font` | HIGH | `agent` |
| `constitution.layer-violation` | HIGH | `agent` |
| `constitution.root-markdown` | MEDIUM | `agent` |
| `constitution.single-use-script` | MEDIUM | `agent` |
| `constitution.commit-message-shape` | MEDIUM | `agent` |
| `constitution.new-ui-literal` | MEDIUM | — (owner summary only) |
| `constitution.resolved-snapshot-stale` | HIGH | `command`: `taller resolve` |
| `constitution.resolved-snapshot-modified` | BLOCKER | `escalate` |
| `constitution.override-without-reason` | HIGH | `escalate` |
| `constitution.override-expired` | HIGH | `escalate` |
| `constitution.override-not-permitted` | BLOCKER | `escalate` |
| `constitution.unknown-rule-id` | MEDIUM | `escalate` |
| `size.file-too-long` | MEDIUM | `escalate` |
| `size.function-too-long` | MEDIUM | `agent` |
| `size.duplicate-block` | LOW | — |
| `tests.failed` | BLOCKER | `agent` — **restricted, see below** |
| `tests.error` | BLOCKER | `escalate` |
| `smoke.boot-failed` | BLOCKER | `escalate` |
| `smoke.route-error` | BLOCKER | `agent` — **restricted** |
| `smoke.not-rendered` | HIGH | `escalate` |
| `smoke.timeout` | HIGH | `escalate` |
| `smoke.unmapped-template` | MEDIUM | — (owner summary only) |

Rationale for the four `escalate` rows that carry a BLOCKER or HIGH: a suite that
could not run, an application that will not start, and a snapshot that was edited
are **environment or intent failures**, not code defects — two LLM rounds are the
wrong response and would burn a fix budget producing nothing. A file over the
length threshold needs a decision about how to split it, which is the architect's
work on a `full` ticket, not a fixer's.

**The fixer may not modify tests.** No fix round may touch any path under
`paths.tests_dir`, or any file matching `test_*.py` / `*_test.py`. The cheapest
way to make a failing test pass is to change the test, and a system that is
allowed to do that cannot be trusted by the person relying on it.

This is enforced **by the harness, not by the prompt**: the fixer's
`Dispatch.forbidden` carries those globs, which render as `--disallowedTools`
specifiers, and a role with a non-empty `forbidden` list is additionally denied
unrestricted `Bash` (§3.6.1). It is a capability the fixer does not have, rather
than an instruction it is asked to respect. `fixer.md` states the rule too, so the
model is not surprised by a denial, but the guarantee is the flag. Asserted in
§15.1.

The three LLM gates assign severity and remediation per finding, from guidance in
their agent definition, and their rule ids are declared there. **Every
security-gate rule is non-suppressible** regardless of severity (§4.5).

Coverage is reported as a `metrics` figure (§7.4), not as a rule. With
`min_coverage_pct: 0` shipped, a coverage *finding* could never fire, so there is
no `tests.coverage-below-minimum` id; a project that sets a non-zero minimum gets
`tests.coverage-below-minimum` at MEDIUM, `escalate`.

### 9.8 Amendment, not argument

A gate the owner can talk out of is not a gate. When a rule is wrong, the rule
changes via `/taller:amend`, which commits the amendment and refreshes the
snapshot — or is suppressed with a written reason via `overrides.md` (§4.5).
Gates do not accept justifications at review time. This is the mechanism intended
to prevent the decay visible in `REFACTORING_PLAN.md` →
`REFACTORING_PLAN_ORIGINAL.md` → `CONSOLIDATED_REFACTORING_PLAN.md`.

---

## 10. Components and build order

### 10.1 Program layout

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
├── templates/catalogue/           INERT generic stock (§4.0)
│   ├── modules/    profiles/    scaffolds/<profile>/manifest.yml + files
├── src/taller/                    THE single implementation (§3.5)
│   ├── cli.py                     argument parsing only
│   ├── inference.py               THE only caller of `claude`          (§3.6)
│   ├── constitution.py            resolve() -> RuleSet; snapshot write  (§4.4, §4.6)
│   ├── overrides.py               parse, match, downgrade               (§4.5)
│   ├── registry.py                ~/.taller/projects.json
│   ├── discovery.py               disk + gh scan, palette clustering    (§4.7)
│   ├── scaffold.py                catalogue copy, manifest substitution (§11.4)
│   ├── gitio.py                   main worktree, commit_to_main         (§7.3)
│   ├── tickets.py                 CRUD, transition                      (§7)
│   ├── locking.py                 project + hub + registry locks        (§10.3)
│   ├── models.py                  alias resolution, probe result, fallback
│   ├── settings.py                effective view + writes by layer   (§5.2)
│   ├── billing.py                 mode detection, weights, pricing   (§5.2)
│   ├── spend.py                   transcript parsing, weighting         (§7.5)
│   ├── brands.py                  derive, write, swatch page
│   └── gates/
│       ├── constitution.py  size.py  tests.py  smoke.py
├── cockpit/                       Flask application
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
| `discovery.py` | Find candidate projects and brands | `scan_disk(roots)`, `scan_remote()`, `reconcile()` → buckets (§4.7), `cluster_palettes(projects)`, `find_brand_assets(path)` | filesystem, `gh` |
| `scaffold.py` | Materialise a catalogue scaffold | `load(profile)`, `render(manifest, answers) -> {path: bytes}` | catalogue files only |
| `constitution.py` | Resolve both chains; render and load generated artefacts | `load_hub_config() -> HubConfig` (§4.4.1), `resolve(path) -> RuleSet` (**pure, writes nothing**), `render_snapshot(rs) -> bytes`, `render_tokens(rs) -> bytes`, `render_index(rs) -> bytes` (§3.1), `load_snapshot(path) -> RuleSet` | `registry`, `overrides`, filesystem (reads only) |
| `gitio.py` | The `main` worktree and the only write path to it | `ensure_main_worktree(p)`, `commit_to_main(p, files, msg) -> SyncState` | git, network, `locking` |
| `overrides.py` | Parse `overrides.md`; downgrade matching findings | `parse(text) -> [Override]`, `apply(findings, ruleset) -> [Finding]` | nothing but its arguments |
| `tickets.py` | Create, read, update, list, transition tickets | `create()`, `load(id)`, `save(t)`, `list(p)`, `transition(t, stage)` | filesystem, `gh`, `locking`, `gitio` |
| `inference.py` | Perform one act of inference; the only module that spawns `claude` | `infer(Dispatch) -> Result` (§3.6) | the `claude` CLI, `RuleSet` |
| `locking.py` | Serialise writes | `project_lock(p)`, `hub_lock()`, `registry_lock()` — context managers | filesystem |
| `models.py` | Resolve aliases; read the probe result; apply fallback | `resolve(role, ruleset)`, `load_probe()` | `RuleSet`, `models-probe.json` |
| `spend.py` | Fold a dispatch's usage into the ticket; weight and total it | `fold(ticket, result)`, `for_ticket(t) -> Spend` (§7.5) | `tickets`, `locking`, and transcript files for the fallback path only |
| `gates/*.py` | Findings for one dimension | `run(diff: Diff, ruleset)`; `scan(tree, ruleset)` except smoke | nothing but its arguments |

`Diff` is what makes the gates pure, so it must carry everything they inspect —
three constitution rules are otherwise uncomputable from a bare patch:

```python
Diff = {
    "base": str, "head": str,                    # commit shas
    "commits": [{"sha": str, "message": str}],   # → constitution.commit-message-shape
    "files": [{
        "path":    str,
        "status":  str,                          # added | modified | deleted | renamed
                                                 #   → root-markdown, single-use-script,
                                                 #     both defined on NEW files only
        "added":   [{"line": int, "text": str}], # → new-ui-literal, brand.hardcoded-*
        "removed": [{"line": int, "text": str}],
        "content": str | None,                   # full text, for whole-file rules
    }],
}
```
| `brands.py` | Derive, write and render a brand | `from_pdf()` (§4.2, the preferred source), `from_css()`, `from_image()`, `write()`, `swatch()` | filesystem, `pypdf`, `pillow` |
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

**Locks are re-entrant within a *thread*, not merely within a process.** A
process-wide counter would let one cockpit thread believe it holds another
thread's lock, and §12's cockpit is a threaded server. A second thread falls
through to the exclusive-create spin, which is the real mutex.

**Semaphore slots are taken non-re-entrantly** (§3.6). A re-entrant lock used as a
counting semaphore silently stops capping, because the second acquisition in the
same thread succeeds by design.

**A lock whose owning process is gone is reaped.** The holder's PID is written into
the lock file so it can be read back: without that, a process killed by the OS or
lost to a power failure leaves a lock that blocks every later invocation and can
only be cleared by hand.

**Locks are re-entrant within a process.** §7.6 holds the project lock for the whole
of a chief dispatch, and a stage transition inside that window calls
`gitio.commit_to_main()`, which takes the same lock. A non-re-entrant lock would
deadlock against itself and fail after 5s on the system's most common path.
`locking.py` therefore keys a recursive counter by lock path and process, releasing
only when the outermost holder exits.

### 10.4 Build order

**The pilot is a greenfield project first.** Phase A proves itself by running
`taller project new` on an empty hub into a throwaway repository, and only then by
adopting an existing one. Greenfield is the cheaper proof and the primary entry
point (G0); adoption is the harder case and goes second.

| Phase | Contents | Effort | Delivers |
|---|---|---|---|
| **A** | CLI flag verification (§3.4); **`inference.py`** with bootstrap mode (§3.6); `HubConfig` + `load_hub_config()` (§4.4.1); empty-hub contract + catalogue; `~/.taller-run/`; slice vocabulary; both resolution chains; `overrides.md` + non-suppressible predicate; `render_snapshot` / `render_index` / `render_tokens`; `taller.yml` inheritance; `locking.py` (re-entrant); `main` worktree + `commit_to_main()` incl. no-remote mode; `taller setup` discovery; `project new` + scaffolds + `queue.yml`; `project adopt`; `project brief`; brands incl. `from_pdf()` | ~4 sessions | G0, G1, G3, G8, G9 |
| **D** | Tickets, `status.yml`, `sync` handling, transitions, issue mirroring | ~1 session | G5 |
| **B** | Chief, routing, lanes, per-ticket sessions, model roster, `models probe`, `spend.py`, `billing.py`, `settings.py` | ~2 sessions | G2, G6, G7 |
| **C** | Gates — constitution first, then size/tests/smoke, then the three LLM gates. `scan()` mode. `project adopt` removes the superseded `code-review/`, `security-review/`, `design-review/` directories. | ~2–3 sessions | G4 |
| **F** | GitHub wiring, `taller-ci.yml`, branch ruleset, staging environment | ~1 session | — |
| **E** | Cockpit | ~2–3 sessions | G7 made visible |

**Why `locking.py` and `commit_to_main()` are in A, not D.** `project adopt`
(§11.3) must write the first snapshot and the first `tokens.css`, and §7.2 makes
`commit_to_main()` the only writer of either. Phase A therefore cannot ship
onboarding without them. They live in `gitio.py` rather than `tickets.py` so that
the phase boundary matches a module boundary: A delivers the write path, D
delivers tickets on top of it.

Criterion-to-phase mapping lives in **one place only**, §16. This table names
goals, never criterion numbers, so the two cannot drift.

Each phase is independently useful. A and D alone address §1.1 and §1.3. **Each
phase gets its own implementation plan**, written when the previous phase is
complete.

---

## 11. Onboarding

### 11.1 One question list, two entry points

`taller project new <name>` and `taller project adopt` run the **same twelve
questions**, in four short rounds. `adopt` arrives with more of them pre-filled
from the repository; `new` has nothing to derive from, so it needs *more*
conversation, not less.

**Round 1 — what it is**

| | Question | Feeds |
|---|---|---|
| ① | In one sentence, what does this do? | `product.md` |
| ② | **What does it deliberately NOT do?** | `never.md` |
| ③ | What must never break? | `product.md`; seeds `paths.security_sensitive` |

② is the question that keeps a tool from quietly becoming a different, larger
tool. Nothing in the repository can answer it and it is never asked by default.

**Round 2 — who and where**

| | Question | Feeds |
|---|---|---|
| ④ | Who uses it — you alone, a team with roles, or the public? | The auth architecture, and whether the security module is `web-app` or `minimal`. Changing this later is a rewrite, so it is asked before any code exists. |
| ⑤ | Reached from where — this machine, a private network, a VPN, or the internet? | Reverse proxy, TLS, compose files, staging |
| ⑥ | Used on a phone? | The `ux` slice; whether mobile is a gate concern |

**Round 3 — data**

| | Question | Feeds |
|---|---|---|
| ⑦ | What does it store? | Schema scaffold |
| ⑧ | **Does any of it involve money, personal data, or credentials?** | Sets `paths.security_sensitive`, makes the security gate mandatory on those paths, and scaffolds audit logging |

**Round 4 — shape**

| | Question | Feeds |
|---|---|---|
| ⑨ | Profile — a picker over the hub, plus the catalogue, plus `create new…` | Stack, modules |
| ⑩ | Brand — a picker over the hub, plus `new brand…`, plus `none` | `tokens.css` |
| ⑪ | Deploys where? | compose, staging, and the `smoke.boot` command |
| ⑫ | **What is the smallest version that is actually useful to you?** | Becomes the **first three to five tickets** |

⑫ exists so that onboarding does not end with an empty project and a blank
prompt. It ends with a board that already has work on it.

**Then review.** A one-page **project brief** is rendered as a standalone HTML
file and opened locally — what it is, what it is not, who uses it, what must never
break, the stack, the brand swatch (§4.2), the deploy target, and the first
tickets. Approve, edit a specific answer, or cancel.

**Nothing is written into the project before the brief is approved.** The single
exception is the resume file at `~/.taller-run/onboarding/<name>.yml`, outside any
project.

**An unconfigured hub is handled, not assumed away.** `language` is asked at
`taller setup` round 5 (§4.7), which a first-ever `taller project new` will not
have run. Rather than making `setup` a precondition the owner has to know about,
`project new` detects `language: null` — or an empty hub generally — and runs
`setup` **rounds 1 and 5** inline first, then continues into the twelve questions.
Round 2 (project roots) is deliberately skipped: only rounds 3–4 consume it, and
neither runs here, so asking would collect an answer nothing reads.
The twelve are unchanged and unrenumbered; the prerequisites simply get collected
when they are missing. A project must never be created with `language` unset,
because §8.2's `constitution.new-ui-literal` and the UX gate's language rule both
guard on it and would silently do nothing.

### 11.1.1 The brief is re-runnable

`taller project brief` reopens the same twelve questions with the current answers
filled in. Changes are written as constitution amendments (§9.8), so they carry
history and can be reverted.

This exists because a week into a project the answers are better than they were on
day one — particularly ② and ⑧ — and a constitution that cannot be corrected stops
describing the program. That drift is the mechanism behind the pattern in A.3,
where a repository accumulates `PLAN.md`, `PLAN_ORIGINAL.md` and
`CONSOLIDATED_PLAN.md` because no document was allowed to be the current one.

### 11.2 Derive facts, interview intent

The machine extracts what is observable: stack, dependencies, directory
structure, existing CSS custom properties, route patterns, naming conventions,
test layout, git history, and a candidate `smoke.boot` command (`run_local.py`,
`wsgi.py`, `docker-compose.yml`). It asks the owner only what is not in the code:
purpose, users, what must never break, brand intent, priorities.

On adoption this leaves six to eight questions rather than twelve, and the ones
left are exactly those no repository scan could answer.

### 11.3 Properties

- One question at a time, with a recommended default in brackets.
- Inferred facts are shown for correction rather than requested as input.
- **Resumable** — answers written to `~/.taller-run/onboarding/<name>.yml` as
  given, so a dead session does not restart the interview. Deleted on completion.
- `adopt` diffs the derived local constitution against the hub and **deletes what
  is already shared**, so adoption reduces text rather than adding it.
- `adopt` creates the `main` worktree (§7.3), writes the first snapshot (§4.6),
  and registers the project.
- `adopt` on a project with superseded review directories — copied-in agent
  definitions or CI workflows that the gates now supersede — proposes their
  removal (Phase C).
- Both entry points work on a repository with **no** existing `CLAUDE.md`, no
  design tokens, and no git history. Nothing is inferred from their absence except
  that there is nothing to lift.

### 11.4 What `taller project new` creates

The catalogue ships one scaffold per profile (§4.0). A scaffold is a **template
directory plus a substitution manifest**, not generated code — so it is auditable,
and editable by the owner without touching Python.

```
templates/catalogue/scaffolds/flask-sqlite/
├── manifest.yml               which files, which substitutions, which are stubs
├── app.py.j2                  wsgi.py.j2 · run_local.py.j2
├── routes/__init__.py.j2
├── database.py.j2             WAL, sqlite3.Row, get_db() context manager
├── templates/base.html.j2     links static/css/tokens.css
├── requirements.txt.j2        pinned
├── docker-compose.yml.j2      docker-compose.staging.yml.j2 · Caddyfile.j2
├── .github/workflows/taller-ci.yml
├── tests/conftest.py.j2       fixture database — never a live file
├── .gitignore                 *.db, *-wal, *-shm, venv/, .env, *.egg-info/
├── .gitattributes             eol=lf everywhere; merge=ours for generated files.
│                              Not optional: without it the §4.6 tamper check
│                              fires on a clean checkout on Windows.
└── README.md.j2
```

`manifest.yml` declares, per file, whether it is copied verbatim, substituted, or
**omitted** when an answer makes it irrelevant — no Docker files when ⑪ says local
only, no auth scaffolding when ④ says single operator, no audit logging when ⑧ says
no money or personal data. A scaffold is shaped by the answers, not pasted whole.

Taller then adds what every project gets regardless of profile:

| Added | From |
|---|---|
| `.taller/constitution/` | The twelve answers |
| `.taller/queue.yml` | Answer ⑫, as **proposed** tickets — see the phase note below |
| `.taller/resolved.json` | `resolve()` + `commit_to_main()` (§4.6) |
| `static/css/tokens.css` | `render_tokens()` (§4.2.1) — omitted when brand is `none` |
| `CLAUDE.md` | Stub pointing at `00-index.md` |

Finally: **`git init -b main`** (the branch name is required, §7.3), one commit,
`ensure_main_worktree()` (which needs that commit to exist, §7.3), and — **only if asked** — `gh repo create --private`. No remote is
created without the owner saying so (§13.2), so the greenfield path normally lands
at `sync: local`.

**Phase boundary for answer ⑫.** Onboarding is Phase A; tickets are Phase D. So
`project new` writes answer ⑫ as `.taller/queue.yml` — a list of proposed pieces of
work, in the owner's own words — and **does not create ticket folders**. Phase D adds
`taller ticket new --from-queue`, which converts each entry into a real ticket and
empties the queue. §11.1 ⑫'s promise that onboarding "ends with a board that already
has work on it" is therefore true from Phase D onward; in Phase A it ends with a
queue, which `taller project show` prints. This keeps Phase A free of the ticket
machinery it would otherwise have to build early.

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
| Spend | `weighted_tokens` by ticket, week and model; currency **only when `billing.mode == api`** (§5.2). `partial: true` marked as lower bounds; tickets past `per_ticket_warn` amber. |
| Constitution | Read and edit rules; saving commits the amendment under the hub lock and refreshes affected snapshots. |
| **Settings** | Every effective key with the layer it resolved from (§5.2), editable. Shows `billing.mode`, and hides `pricing` and `cost` entirely when the mode is not `api`. |
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
| Branch protection | Ruleset: require a pull request, require `taller-ci` green. Admin bypass retained for `gitio.commit_to_main()` only. |
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
| `BLOCKER` survives `max_fix_rounds` | Stop. Set `blocked` (§8.4), keeping the stage. Escalate with what was attempted and why it failed. Never proceeds quietly. |
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
| Two writers at once, or two chief dispatches on one ticket | Project, hub or registry lock + atomic replace (§10.3); the project lock is held for a whole chief dispatch (§7.6). Loser fails clearly after 5s. |
| Ticket rejected at ⑦ | `chief_session` cleared; a fresh conversation starts at ②, briefed from `notes.md` (§7.6). |
| Ticket resumed in a Claude Code session | The ticket's conversation is not reachable there; the chief is briefed from disk instead (§7.6). Files lose nothing; unwritten conversation does. |
| A dispatch is killed (SIGTERM) | Exit 143, turn unfinished, no result recorded. `infer` reports an error rather than an empty success (§3.6). |
| `claude -p` starts defaulting to `--bare` | Subscription auth would break silently. `doctor` asserts a trivial dispatch succeeds with no `ANTHROPIC_API_KEY` set (§3.6.2). |
| Spend cannot be fully attributed | `spend.partial: true`; rendered as a lower bound. Never estimated. |
| `billing.mode` is not `api` | `spend.cost: null` by design; the cockpit shows weighted tokens only and hides cost entirely (§5.2). |
| `pricing.as_of` older than 90 days, with mode `api` | `doctor` reports it stale; `cost` is still computed but flagged as based on an old table. |
| Detected billing mode differs from the configured one | `doctor` reports the mismatch — e.g. an `ANTHROPIC_API_KEY` appeared since setup, so budgets now mean money. |
| Usage window exhausted mid-ticket (`subscription`) | The dispatched agent fails; the ticket blocks at its current stage with the reason recorded. `concurrency` exists to make this rare (§5.2). |
| Snapshot older than the hub | `constitution.resolved-snapshot-stale` HIGH; remediated by `taller resolve`, a command, not an agent (§9.7). |
| Snapshot edited by hand, or carried on a branch | `constitution.resolved-snapshot-modified` BLOCKER, escalated to the owner. Locally by byte-for-byte re-resolution; in CI by detecting the diff (§4.6). |
| Amend touches a module six projects share | All six snapshots refreshed, each under its own lock; `/taller:amend` reports which projects it wrote. Any that fail leave `sync: pending` (§4.6, §7.3). |
| Test suite could not run, or application will not boot | `escalate` — the owner is asked. No fixer round is spent on an environment failure (§9.7). |
| Fixer attempts to modify a test file | Round aborted, escalated. Never permitted (§9.7). |
| Smoke route returns 3xx to a login page | `smoke.not-rendered` HIGH — a redirect is not a render (§9.6). |
| `smoke.auth.secret` unset | `taller doctor` reports it; the gate escalates rather than failing opaquely. |
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
- Snapshot: `render_snapshot()` then `load_snapshot()` round-trips a `RuleSet`
  including slice text and brand tokens; `render_snapshot()` is byte-stable across
  two calls; `resolve()` writes **no** file (assert the tree is unchanged after a
  call); `mode` is `"local"` from `resolve()` and `"ci"` from `load_snapshot()`.
- Snapshot check ordering: `hub_sha` behind the hub `HEAD` gives **stale** only,
  never modified, even though the bytes differ; `hub_sha` current plus altered
  bytes gives **modified**; the check writes nothing.
- Brand delivery: `render_tokens()` reproduces the hub brand's `tokens.css`
  verbatim and `commit_to_main()` writes it; the constitution gate exempts that
  path and flags an identical value placed anywhere else; adopting a project whose
  tokens live in another file lifts them to the hub rather than reporting them
  (§4.2.1).
- Fixer restriction: a fix round attempting to write under `paths.tests_dir`, or
  to `test_*.py` / `*_test.py`, aborts and escalates.
- Remediation routing: `tests.error`, `smoke.boot-failed`, `smoke.not-rendered`
  and `size.file-too-long` escalate without dispatching a fixer;
  `constitution.resolved-snapshot-stale` runs `taller resolve`.
- `overrides.py`: valid suppression downgrades to `NIT` with the reason attached;
  missing reason; expired `until` (distinct rule id from missing reason); a
  rule id in the resolved `non_suppressible` list and any security-gate rule are
  both refused (§4.5); an id in that list that no gate declares is reported as
  `constitution.unknown-rule-id`.
- `spend.py`: recorded transcript fixtures, including one unattributable record
  asserting `partial: true`; `weighted_tokens` differs from `total_tokens` on a
  cache-heavy fixture; `cost` stays `null` on every `billing.mode` but `api`.
- `locking.py`: two writers, one wins, the loser fails within 5s, the file
  survives intact.
- `inference.py`: the `Dispatch` → argument mapping of §3.6, for every field; a
  `ruleset: None` bootstrap dispatch builds correctly from `model`/`effort`/`system`
  alone; a non-zero exit, unparseable JSON, a schema mismatch, exit 143 and a missing
  `claude` binary each return `ok: false` with a distinct reason and **no retry**;
  `session_id` is captured from the result and replayed as `--resume`; `--bare` is
  never passed; `concurrency` caps in-flight dispatches **across two processes**, not
  just within one.
- `forbidden` rendering (§3.6.1): each glob expands to `Write(...)`, `Edit(...)` and
  `NotebookEdit(...)` specifiers; a role with a non-empty `forbidden` list never
  receives bare `Bash`; the `main` worktree never appears in `--add-dir`. Assert on
  the generated argument list, since this is the mechanism §9.7 depends on.
- `spend.py`: per-dispatch `usage` accumulates while a **resumed** session's
  cumulative `cost_usd` does **not** — a three-stage ticket must not report three
  times the chief's spend; the transcript fallback resolves the worktree's slug
  rather than the project's.
  Tested against a stub `claude` on `PATH`, so the suite makes no real inference calls.
- `discovery.py`: `reconcile()` produces the four buckets of §4.7 from fixture disk
  and `gh` output, including a local repository whose remote does not resolve;
  `cluster_palettes()` groups two identical palettes and separates a drifted one;
  `find_brand_assets()` locates a logo and a brand-guide PDF.
- `scaffold.py`: `render()` substitutes every manifest variable; a manifest omission
  fires for each documented condition — local-only deployment, single operator, no
  money or personal data; an unknown variable is an error, not a blank.
- `settings.py`: `show` reports the layer each value resolved from; `set` writes a
  project key to the project file and a shared key to the hub, under the right lock;
  a key that exists in no layer is rejected rather than invented.
- `billing.py`: each of the four modes detected from its environment variable;
  `cost` stays `None` on every mode but `api`; `pricing.as_of` older than 90 days
  is reported stale.
- A **copy of a catalogue profile brings its modules** and never overwrites a module
  already in the hub (§4.0).
- `commit_to_main()`: non-fast-forwardable `main` is rebased and succeeds; a
  rejected push leaves `sync: pending` and loses no transition; the next call
  retries the push first.
- `gates/smoke.py`: `kind: http` boot failure, route 500, 302-to-login producing
  `smoke.not-rendered`, timeout with the subprocess reaped, two concurrent runs
  getting distinct ports, `data: copy` leaving the source database and its `-wal`
  file untouched; `kind: import` raising; `kind: none` passing with
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
- a `non_suppressible` entry, and an override targeting it (must be refused)
- a project attempting to REMOVE a hub `non_suppressible` entry (must not succeed)
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
| The `claude` CLI is present at or above `cli_min_version`, and **every flag in §3.6's mapping table is accepted** by `claude --help` (§3.4) | A |
| A trivial dispatch succeeds **with no `ANTHROPIC_API_KEY` set** — proving subscription auth still works and `--bare` has not become the default (§3.6.2) | A |
| Every profile in the hub names only modules the hub contains (§4.0) | A |
| `language` is set — not `null` — for every registered project (§11.1) | A |
| `resolve()` succeeds; no unreasoned, expired or non-permitted override | A |
| `resolved.json` present, not stale, and byte-identical to an **in-memory** `render_snapshot(resolve(path))` — nothing written | A |
| `merge.ours.driver` is configured, so `.gitattributes`' `merge=ours` is not decoration (§4.6) | A |
| No lock left behind by a dead process (§10.3) | A |
| **When `brand` is not `none`:** `paths.brand_tokens` present and byte-identical to an in-memory `render_tokens()`. Skipped with reason when the brand is `none`, so `python-packaged` passes. | A |
| `00-index.md` present, byte-identical to an in-memory `render_index()`, and within its 600-token budget | A |
| No ticket branch carries its own `resolved.json`, `00-index.md` or brand tokens | A |
| Registry valid; every registered path exists; every `main` worktree present | A/D |
| Every `status.yml` parses; no ticket left `sync: pending` (`local` is fine) | D |
| Every configured model reachable, per the last `taller models probe` result | B |
| `billing.mode` matches the detected environment; `pricing.as_of` within 90 days when mode is `api` (advisory) | B |
| Every Python gate executes; `smoke` configuration valid for the profile; `smoke.auth.secret` resolvable if declared; each LLM gate **dry-runs** — prompt assembles and its model appears reachable in the cached `models-probe.json`, with no inference performed | C |
| Latest `taller-ci` run on `main` with `taller-ci-mode: full` is green (§9.4) | F |

The dry-run rule keeps `taller doctor` free to run.

### 15.5 The greenfield path is tested end to end

`taller project new` is the primary entry point (G0), so it gets the heaviest
integration test, not the lightest:

1. Point `HOME` at an empty temporary directory — **a hub with nothing in it.**
2. Run `project new` with scripted answers to the twelve questions, once per
   catalogue profile.
3. Assert `taller doctor` passes every check the built phases provide, with none of
   those skipped. Checks belonging to unbuilt phases report skipped-with-reason
   (§15.4) and do not fail the test.
4. From Phase C: assert the smoke gate boots the result and returns 200 with a body.
5. Assert `queue.yml` exists with the entries answer ⑫ implied. From Phase D: assert
   `ticket new --from-queue` converts them. From Phase B: assert one runs ① → ⑩.
6. Assert `manifest.yml` omissions held: no compose files when the answer was
   local-only, no auth scaffolding when the answer was single-operator, no audit
   logging when the answer was no money or personal data.

Step 1 is the important one. A test that runs against a populated hub would pass
while `project new` silently depended on something a real first-time install does
not have.

### 15.6 The plugin is tested for ignorance

A **domain vocabulary list** lives in `tests/domain_vocabulary.txt`: brand names,
business-specific nouns, project names, and words in any language other than the
plugin's own English. A test asserts that **no file in the plugin repository
contains any of them**, excluding that list itself and the fixtures under
`tests/fixtures/`.

This makes G9 checkable rather than promised. The catalogue is inside the plugin
(§4.0), so it is covered too: a catalogue entry that acquired a brand default or a
non-English UI string turns the test red.

A second test asserts a **fresh hub is empty** — no brands, no profiles, no
modules, no registered projects, and `language: null`.

### 15.7 Acknowledged limitation

The three LLM gates are non-deterministic. Fixture tests reduce the risk; they do
not eliminate it. A gate will occasionally miss a real problem. This is why owner
checkpoint ⑦ exists and why `main` requires green CI — defence in depth rather
than one perfect filter.

---

## 16. Acceptance criteria

**This table is the only phase↔criterion mapping in the document.**

Every criterion is stated against **any** project, so the same table applies to a
greenfield project and to an adopted one. Appendix A gives the numbers that the
adoption criteria were calibrated from.

**Greenfield — the pilot path (§10.4):**

| # | Criterion | Target | Phase |
|---|---|---|---|
| 1 | A fresh install has an empty hub: no brand, no profile, no project, no `language` | verified on a clean machine | A |
| 2 | `taller project new` on an empty hub produces a repository that **passes every `taller doctor` check Phase A provides**, with none of those skipped | passes | A |
| 3 | That repository **boots under the smoke gate** on its first commit | passes | **C** — smoke is built in C (§10.4) |
| 4 | Answer ⑫ lands as `queue.yml` (A); `ticket new --from-queue` converts it (D); one of those tickets runs ① → ⑩ end to end (B) | passes | A → D → B |
| 5 | The plugin repository contains **no occurrence of the domain vocabulary list** (§15.6) | 0 | A |

**Adoption:**

| # | Criterion | Baseline (A) | Target | Phase |
|---|---|---|---|---|
| 6 | An adopted project's always-loaded preamble | up to ~7,000 tokens | ≤ 800 tokens | A |
| 7 | Authored local content, for any two projects sharing a profile | 9,466 chars each, identical | < 2,000 chars each | A |
| 8 | `taller setup` registers every discovered project and reports every unresolvable remote | manual, one at a time | one pass | A |
| 9 | Brands created by confirming a discovered cluster rather than typed from scratch | 0 | every brand with a discoverable palette | A |
| 10 | Review directories duplicated across projects | 6 projects | 0 | C |

**Mechanics, independent of how the project arrived:**

| # | Criterion | Target | Phase |
|---|---|---|---|
| 11 | Ticket resumable after a killed session | every ticket | D |
| 12 | Tickets with a recorded `weighted_tokens` figure | every ticket | B |
| 13 | Owner approval checkpoints before production | 2 unconditional + 2 lane-dependent, enforced | B |
| 14 | Tickets reaching ⑩ merge with an unsuppressed `brand.hardcoded-*` finding in their own constitution verdict | 0 | C |
| 15 | `taller scan` produces Health figures for every registered project | all | C |
| 16 | CI workflows per repository | 1 | F |
| 17 | Staging environment per project whose profile defines one | one each | F |
| 18 | `taller doctor` green on every registered project, no check skipped | passes | F |

**Criterion 7** counts authored local content — `product.md`, `architecture.md`,
`never.md`, `overrides.md` — and **excludes the generated `00-index.md`** (~40
lines by design) and `resolved.json` (generated). Without those exclusions the
criterion would be arithmetically unreachable.

**Criterion 14** measures G4 exactly, against the ticket's own verdict rather than
a repository count. A ratchet on a scan total would pass a ticket that removes one
hardcoded value and adds another — the count stays flat while a new value reached
`main`, which is precisely what G4 forbids. The verdict is already on disk
(§7.4), so the measure is: no ticket merges with an unsuppressed
`brand.hardcoded-color` or `brand.hardcoded-font` finding of its own. Findings
downgraded by an active override (§4.5) are excluded, because §4.5 exists to admit
reasoned exceptions.

The `taller scan` total remains the **trend figure** on the Health screen, which
is a different and also useful question.

**Criterion 18** is Phase F because doctor checks CI (§15.4), which does not exist
until F.

**Consequences, not deliverables** — tracked, not gated on: pre-existing
violations in an adopted project (A.3, A.4) are not Taller's to fix as part of its
own construction. Taller **generates tickets** for them (§2, §18); `taller scan`
counts them and the Health screen shows them trending down.

---

## 17. Decisions and rejected alternatives

| Decision | Rejected | Reason |
|---|---|---|
| **Taller is a standalone program that drives the `claude` CLI as a subprocess** | A Claude Code plugin only; embedding the Claude Agent SDK | The owner needs a program usable instead of, or interchangeably with, Claude Code. Embedding the Agent SDK would have forced API-key billing — its terms do not permit a third-party product to run on a claude.ai subscription — and the owner's stated preference is the subscription. Driving the owner's own authenticated CLI is the documented route for exactly this, and is the same relationship Taller already has with `gh`. |
| **A persistent chief, with a session per ticket** | A chief that merely arrives briefed each session | Once Taller is the program, Taller is the process, so the concession is unnecessary. `--session-id` per ticket means the chief's conversation survives across stages and days, not just its briefing. |
| **All inference behind one module, `inference.py`** | Spawning `claude` wherever a model is needed | It keeps the Agent-SDK option a one-module swap, it is the only place that can enforce `concurrency`, and it is where path restrictions become harness-enforced rather than merely requested. |
| **`--disallowedTools` specifiers enforce the no-test-file rule, plus no bare `Bash`** | Enforcing it in `fixer.md` alone; passing bare paths to the flag | A capability the fixer does not have beats an instruction it is asked to respect — but `--disallowedTools` takes tool specifiers, not paths, so a path would have restricted nothing silently, and a shell could have circumvented the specifiers anyway (§3.6.1). |
| **`--bare` is never passed, and `doctor` asserts subscription auth still works** | Using the documented recommended mode for scripted calls | Bare mode never reads OAuth credentials, so it requires an API key — it would silently destroy the billing arrangement this design was chosen for. It is also slated to become the `-p` default, which makes this the largest forward-compatibility risk in the design and worth a standing assertion rather than a comment. |
| **Only the chief holds a session; specialists are one-shot** | A session per role, or per (ticket, role) | A specialist's output already persists as a plan, a diff or a verdict file, so a conversation would add cost without adding memory — and one id per ticket removes the schema and resume ambiguity. |
| **The chief's session is abandoned on rejection, kept on promotion** | Keeping it in both cases | A conversation holding a rejected plan and deleted code is worse than a clean start plus the written reason; a promotion is mid-ticket with the diff retained, so continuity helps. |
| **Per-dispatch `usage` for spend, not cumulative `cost_usd`** | Summing the reported cost per dispatch | A resumed session reports the whole conversation's total, and the chief's session is resumed at every stage — summing it would have multiplied the chief's spend by the number of stages. |
| **`concurrency` is a cross-process semaphore** | A per-process counter | The limit it protects is a per-account usage window, and the CLI, the cockpit and a session can all dispatch at once. |
| **`billing.mode` detected, with different meanings for budget and concurrency** | One budget model for everyone | On a subscription the binding constraint is a usage window, not money: five parallel gates with one on Opus can exhaust it in minutes, and that failure is not gradual — work stops. `concurrency` bounds it, and `cost` stays `null` because a dollar figure would be fiction. On API billing the same number is a real cost proxy. |
| **`pricing` ships with an `as_of` date, and `doctor` calls it stale at 90 days** | Shipping no table; shipping an undated one | A table is more useful than nothing once it is honest about age. It is also the only part of the configuration that goes wrong while nothing changes locally. |
| **`taller settings` is a single surface over three config layers** | Hand-editing YAML in three places | Resolution is layered by design (§4.4), but reading and changing a value should not require knowing which layer owns it. The command prints where each value came from. |
| **The hub starts empty; the plugin ships an inert generic catalogue** | Shipping profiles, a brand and a UI language as defaults | The first draft shipped a profile with a line of business in its name, a named brand as a profile default, and one human's UI language as a hub default — while claiming on the same page to contain no domain-specific knowledge. "Empty" must mean *knows nothing about you*, not *can do nothing*, so the catalogue exists but is inert until copied. |
| **A domain-vocabulary test (§15.6) and an empty-hub test** | Promising genericity in prose | G9 is otherwise unfalsifiable. The catalogue lives inside the plugin, so it is covered too. |
| **Evidence moved to Appendix A** | A problem statement built from one person's repositories | The measurements are the reason the thresholds are not guesses, but as §1 they made the document read as a cleanup project for one estate — which is how `project new` ended up the least-specified part of a tool whose main job is starting new projects. |
| **Greenfield is the pilot, adoption second** | Piloting on an existing repository | `project new` is the primary entry point (G0). It is also the cheaper proof: an empty hub and a throwaway directory, with no existing mess to confuse a framework failure with a project failure. |
| **`taller setup` discovers projects and brands** | A registry populated one `project adopt` at a time | Nobody registers ten projects by hand twice. Discovery also surfaces what manual registration never would — a broken remote, an uncloned active project, a stack the catalogue does not cover, and six projects of one business carrying five disagreeing palettes (A.6, A.4). |
| **Brands created by confirming a discovered cluster; brand guide PDF preferred over CSS** | `brand new` from a blank prompt; CSS as the source of truth | A stylesheet is an implementation that may already have drifted. A.4 found one authoritative guide and five palettes that disagreed with it and with each other. |
| **Twelve questions in four rounds, including "what does it NOT do" and "what is the smallest useful version"** | The same six questions for `new` and `adopt` | `project new` has nothing to derive from, so it needs *more* conversation, not less. The scope-boundary question is what keeps a tool from becoming a different, larger tool; the smallest-useful-version question is what stops onboarding ending at an empty project and a blank prompt. |
| **The brief is re-runnable, and changes are amendments** | Answered once at creation | A week in, the answers are better than they were on day one. A constitution that cannot be corrected stops describing the program — which is the mechanism behind A.3. |
| **Scaffolds are template directories with a `manifest.yml`** | Generated by code | Auditable, and the owner can edit a scaffold without touching Python. The manifest also omits files the answers make irrelevant, so a scaffold is shaped rather than pasted. |
| Superpowers as the engine, Taller as the addition | Adopt Spec Kit wholesale; build from scratch | Spec Kit is agent-agnostic, so it cannot use Claude Code subagents — the team structure would be lost. It adds a second toolchain (Python CLI + `uv`) and is verbose by design, conflicting with the cost goal. From scratch means re-implementing working brainstorm/plan skills. |
| Tickets as files, GitHub Issues as a mirror | Issues as the store; local SQLite | Agents are the heaviest readers. Files cost no API ceremony and no network. SQLite is a second source of truth that never appears in a pull request diff. |
| **A committed `resolved.json` snapshot** | Give the hub a remote + deploy key; restrict CI to hub-independent checks | CI cannot see a local-only hub, so two of its three gates could not run and no verdict could record `hub_sha`. A snapshot keeps §13.2's local-only default intact, needs no secrets, and makes rule changes visible in the pull request diff. |
| `ticket.md` + `status.yml` + `notes.md` on `main`, via a long-lived `main` worktree, with an explicit `sync` state | Everything on the branch; assuming push always succeeds | In-flight tickets must be visible from `main`; a rejected branch must not destroy its rejection reason; nothing may disturb a live database's write-ahead log; and commit+push is not atomic, so the failure had to become visible rather than assumed away. |
| Runtime state in `~/.taller-run/`, outside the hub repo | Locks and worktrees inside `~/.taller/` | A nested worktree lets a hub amendment sweep a project checkout into the hub, and a hub revert can destroy the worktree Taller commits through. |
| Two separate resolution chains — config and slice text | One "later wins" chain over both | Markdown prose cannot set `thresholds`; a single chain misled about precedence and left `paths` with no project override. |
| Slice text appends; only `overrides.md` suppresses, by rule id, with a reason | Project prose overriding hub prose | Append-vs-override was ambiguous on whether a project can delete a hub prohibition. It cannot. |
| `never` and security rules are non-suppressible | All rules overridable | Otherwise `never` does not mean never, and a security BLOCKER could be downgraded to silence. |
| `paths.security_sensitive` append-only, over a hub floor | Lists replace uniformly | A project able to narrow its own security surface would make the mandatory security gate optional. |
| **Rule ids carry default severities and a `remediation` (§9.7)** | Severity left to the implementer; severity alone deciding who acts | The fixer, the summary and §4.5's downgrade all key off severity. And severity alone routed a suite that would not run and an application that would not boot into an LLM fixer for two rounds — environment failures where that is the wrong response and buys nothing. |
| **The fixer may never modify a test file** | Trusting the fixer's judgement | The cheapest way to make a failing test pass is to change the test. A system allowed to do that cannot be trusted by the person relying on it. |
| **Tamper check: local byte-for-byte re-resolution; CI rejects a branch that carries a snapshot** | Trusting the committed snapshot; relying on the diff being visible | `resolve()` is deterministic, so the snapshot is reproducible — and without the check a branch could raise its own thresholds or delete the `never` text and CI would pass it. `hub_sha` stays correct under a hand edit, so staleness alone catches nothing. Showing a diff in review is not checking it. |
| **`resolve()` is pure; `render_*()` serialise; only `commit_to_main()` writes** | `resolve()` writing and committing the snapshot | A committing `resolve()` would be neither pure nor network-free, would make `constitution.py` depend on `tickets.py`, and would let the tamper check rewrite the very file it is testing — so it could never fail. |
| **Stale is checked before modified** | Both checks at once | Once the hub moves the bytes necessarily differ, so an unordered pair raised a BLOCKER on every ticket in flight during a routine amend — which §14 treats as a warning. |
| **`locking.py` and `commit_to_main()` (in `gitio.py`) ship in Phase A** | Both in Phase D with the tickets | `project adopt` is a Phase A deliverable and must write the first snapshot and `tokens.css`, which only `commit_to_main()` may do. Putting them in `gitio.py` makes the phase boundary a module boundary. |
| **Generated `static/css/tokens.css` inside each project; `adopt` lifts existing tokens into the hub** | The hub `tokens.css` as the deployed file; flagging a project's existing token definitions | The hub is outside the repository and outside the Docker image, so the browser could never load it. And left alone, a project's existing token definitions in another stylesheet would each have been reported as a hardcoded value — adoption would flag the project's own design system. |
| **Smoke isolates data, port and auth; a 3xx is not a render** | A fixed port; whatever database the app config points at; accepting any 2xx/3xx | A fixed port collides with the owner's dev server and with a second ticket. Booting against the live SQLite file risks the WAL that §7.3 and §13.1 both protect. And an application with a login redirects an unauthenticated request to a login page — 302 would have passed while rendering nothing, which destroys the fast lane's only safety argument. |
| **Criterion 6 measured from the ticket's own verdict** | A `taller scan` count ratchet | A ratchet passes a ticket that removes one hardcoded value and adds another: the count stays flat while a new value reaches `main`, which is exactly what G4 forbids. |
| **`mode` in the `RuleSet`** | Gates reading the environment | The local-vs-CI difference is required behaviour and had no channel; putting it in the `RuleSet` keeps `gates/*.py` pure over their arguments. |
| **Rule ids are `<domain>.<rule>`, domains declared per gate** | Ids prefixed by the gate | `brand.hardcoded-color` is found by the constitution gate, so a gate prefix would have made `Finding.gate` and `Finding.rule` contradict each other — and criterion 14 filters on the `brand.` prefix. |
| **Two CI jobs, one required** | One job with an early exit, reporting two names | One job emits exactly one check run, so the informational name had no way to exist — and the required check is the one whose absence deadlocks the merge. |
| Constitution gate fully mechanical; UI-language in the UX gate; `constitution.new-ui-literal` as the fast-lane fallback | A `cheap` model pass in the constitution gate; enforcing language mechanically | Language identification is a heuristic, and a gate that sometimes calls a model cannot promise no per-push cost. The fallback surfaces new strings without judging them, which is decidable. |
| **Smoke fully specified: `kind`, boot, ready, timeout, mapped routes** | Leaving "the application boots" to the implementer | The fast lane's entire safety argument rests on ⑥, and "boots" means nothing for a PyInstaller app or a static site. |
| Both lanes include ②, ⑥, ⑪ and ⑫ | Fast lane as a short prefix | ② loads the slices fast work most needs; ⑥ is the only step that renders a template, and fast work is template editing; omitting ⑪/⑫ meant fast tickets never deployed or closed. |
| ⑤ tests gate = `pytest`; ⑥ smoke = boots and exercises | ⑥ re-running `pytest` | They were the same work with two different recovery mechanisms. |
| Override into `fast` over a security-sensitive path is **refused** | The gate runs anyway on a forced-fast ticket | The two rules contradicted each other. Refusal makes the case impossible. |
| Lane is a prediction; re-laned at ④, including on newly-touched security paths | Lane fixed at ② | Diff size and final paths are not observable at ②. |
| `src/taller/` is the single implementation | "The CLI is the single implementation" | `/taller:new` creates a ticket and `taller project new` creates a project. The shared thing is the library. |
| **`weighted_tokens` for budget; a dated, overridable `pricing` table** | Raw token sum; shipping an undated table; shipping none | In §7.1's own example 65% of tokens are cache reads, which bill ≈ 0.1×, so a raw sum would fire the budget on context re-reads rather than cost. A table is more useful than none once it carries `as_of` and `doctor` calls it stale. |
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
| Commit-message *shape* checked, not language | Enforce a particular summary language | Shape is decidable; language is not. |
| Local-only repositories initially | Create GitHub remotes now | Publishing is the owner's decision, not a design requirement. |

---

## 18. Out of scope

- Refactoring any adopted application, or clearing its pre-existing violations
  (Taller generates tickets for them; it does not do the work as part of its own
  construction)
- Resolving a long-lived divergent branch in an adopted repository (§8.3)
- Multi-user access, authentication, or a hosted cockpit
- Self-hosted CI runners
- Repairing the failing GitHub MCP server (Taller uses `gh`)
- Any fourth profile or module not required by two existing projects
- A tenth slice

---

## Appendix A — Worked example: one real estate

Everything in this appendix is **evidence that the problems in §1 are real**, drawn
from the author's own ten repositories on 2026-09-26. None of it is scope, and none
of it is shipped: the hub starts empty and the catalogue names no business (§4.0,
G9). The numbers exist so the thresholds in §16 were calibrated against something
rather than guessed.

### A.1 Context re-declared (§1.1)

```
8 CLAUDE.md files ................................ 143,487 chars ≈ 36,000 tokens
two of them ........................................ 9,466 chars each, BYTE-IDENTICAL
the largest ....................................... 27,406 chars ≈  7,000 tokens
its sibling context/*.md (3 files) ................ 64,388 chars ≈ 16,000 tokens
```

The largest is loaded in full every session, and again into every subagent that
reads it: ~7,000 tokens of preamble before the first word, ~23,000 if an agent also
reads `context/`. This is the baseline for criterion 6 (≤ 800 tokens) and the two
byte-identical files are the baseline for criterion 7.

### A.2 Review infrastructure copied (§1.2)

`code-review/`, `security-review/` and `design-review/` directories found
duplicated across **six** projects, including one archived copy and one inside a
worktree. Baseline for criterion 10.

### A.3 Work with no home (§1.3)

One repository root contained **40+ ad-hoc planning documents** —
`PHASE4_CHECKPOINT.md`, `SESSION_SUMMARY.md`, `REFACTORING_PLAN.md`,
`REFACTORING_PLAN_ORIGINAL.md`, `CONSOLIDATED_REFACTORING_PLAN.md`, and so on —
plus **~60 single-use scripts** (`fix_*.py`, `check_*.py`, `debug_*.py`,
`diagnose_*.py`) beside application code.

The `PLAN` → `PLAN_ORIGINAL` → `CONSOLIDATED_PLAN` sequence is the pattern §9.8 and
§11.1.1 exist to prevent: when no document is allowed to be the current one, every
session writes a new one.

### A.4 Rules defined and bypassed (§1.4)

One project defined seven CSS custom properties and still contained **26 hardcoded
hex values** in its templates — three of them (`#dc3545`, `#198754`, `#ffc107`)
duplicating tokens that already existed as `--app-danger`, `--app-success` and
`--app-warning`.

Across six projects of the **same business**, design tokens were:

| Tokens defined | Palette |
|---|---|
| 14 | baseline |
| 14 | **identical** to the above |
| 36 | a drifted copy — same hues, shifted values |
| **135** | entirely different (Material-derived) |
| 7 | different again (Flat-UI-derived) |
| **0** | no tokens at all |

Meanwhile an authoritative **brand guide PDF**, with a logo SVG and 22 icons, sat
duplicated inside two of those repositories — and none of the five palettes matched
each other.

This is why §4.2 prefers a brand guide PDF over any stylesheet, why §4.7 discovers
brands by *clustering* rather than asking, and why §4.2.1 lifts existing tokens
into the hub instead of flagging them: left alone, adoption would have reported 33
violations against a real baseline of 26 by flagging the project's own design
system.

### A.5 No staging (§1.5)

Zero occurrences of "staging" across ten repositories. Deployment was Docker
Compose behind a reverse proxy to a private host reachable over LAN and a VPN.

### A.6 What discovery found (§4.7)

Ten local repositories, thirteen remote. Cross-referencing produced:

| Bucket | Count | Notes |
|---|---|---|
| Local **and** remote | 9 | Six on one stack, three on three others |
| Local, remote **unresolvable** | 1 | `origin` pointed at a repository absent from the account listing — most likely renamed |
| **Remote, not cloned** | 4 | One of them pushed **the previous day**, in a language none of the three catalogue profiles cover |
| Local, no remote | 0 | |

Also found: branch conventions used interchangeably (`feat/…` alongside
`feature/…`), and one long-lived divergent branch.

Three findings here are the argument for §4.7 existing at all — a broken remote, an
actively-developed project absent from the machine, and a stack the catalogue does
not cover would all have stayed invisible under a manual, one-project-at-a-time
registration.
