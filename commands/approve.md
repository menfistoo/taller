---
description: Approve a Taller ticket at the checkpoint it is waiting at, then let Taller's team carry on
argument-hint: the ticket number
allowed-tools: Bash(taller ticket approve:*), Bash(taller ticket run:*), Bash(taller --answers:*)
---

The owner approves ticket $ARGUMENTS.

Only the owner approves. If no ticket number was given, ask which ticket they mean
(`/taller:status` lists them); never pick one yourself.

1. Approve it:

   `taller --answers <answers file> ticket approve <number>`

   The answers file is `taller-answers-approve.json` in your temporary directory. If
   Taller prints `NEEDS <id>` (exit code 3), ask the owner that question in plain words,
   add `"<id>": "<answer>"` to the file, and run the same command again.

2. Then carry the ticket on:

   `taller ticket run <number>`

   It can take many minutes: run it in the background and report when it finishes.

3. Tell the owner, plainly, where the ticket stopped and what comes next. If Taller says
   a branch must be merged first, say so; do not merge it yourself.
