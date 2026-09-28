# Taller in a Claude Code chat

The plugin lets you use Taller without leaving a Claude Code chat. It is a remote
control: the chat runs the same `taller` commands you would type in a terminal, asks
you whatever Taller needs to know, and tells you what happened. The work on a ticket is
still done by Taller's own team, exactly as with `taller ticket run`.

## Install

Taller itself must be installed first, so that `taller` runs in a terminal
(`taller doctor` is a good check). Then, in a terminal:

```
claude plugin marketplace add <the folder this repository is in>
claude plugin install taller@taller
```

Or, inside a chat: `/plugin marketplace add <folder>`, then `/plugin install taller@taller`.
Restart Claude Code afterwards.

## The commands

| In a chat | Does |
|---|---|
| `/taller:onboard new <name>` or `/taller:onboard adopt <path>` | Sets Taller up if needed, then creates a project or brings a repository in. The chat asks you the onboarding questions one at a time. |
| `/taller:new <what should be done>` | Starts a ticket in your words and lets Taller's team carry it to the next point that needs you. |
| `/taller:status` or `/taller:status <n>` | Where every open ticket stands, or everything about one. |
| `/taller:approve <n>` | Approves ticket *n* at its checkpoint and carries it on. |
| `/taller:reject <n> <why>` | Rejects it; your reason is where the next attempt starts. |
| `/taller:resume <n>` | Picks a stopped ticket up again. |
| `/taller:amend <the rule>` | Changes a rule with you, then refreshes every project that uses it. |

A chat that opens inside one of your projects starts out knowing it: which project,
its rules, and its open tickets.

## Good to know

- Long runs (a ticket's build, its checks) run in the background; the chat tells you
  when they finish. They can take many minutes.
- Only you approve or reject. The chat never does either on its own.
- When Taller needs an answer, the chat asks you and keeps your answers in a small file
  in its temporary folder, so running a command again never starts over.
