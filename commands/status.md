---
description: Show where the project's Taller tickets stand, or everything about one ticket
argument-hint: optionally, a ticket number
allowed-tools: Bash(taller ticket list:*), Bash(taller ticket show:*), Bash(taller --answers:*)
---

The owner asks about: $ARGUMENTS

1. With no ticket number, list the open tickets:

   `taller --answers <answers file> ticket list`

   With a number, show that ticket:

   `taller --answers <answers file> ticket show <number>`

   The answers file is `taller-answers-status.json` in your temporary directory. These
   commands normally ask nothing; if Taller prints `NEEDS <id>` (exit code 3), ask the
   owner that question in plain words, add `"<id>": "<answer>"` to the file, and run the
   same command again.

2. Summarise it in plain words: what each ticket is, where it stands, and which ones
   are waiting for the owner. Say what the owner can do next, as slash commands
   (`/taller:approve <n>`, `/taller:reject <n>`, `/taller:resume <n>`).
