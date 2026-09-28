---
description: Pick a stopped Taller ticket up again, after a block, a crash or a closed session, and carry it on
argument-hint: the ticket number
allowed-tools: Bash(taller ticket resume:*), Bash(taller ticket run:*), Bash(taller --answers:*)
---

The owner wants ticket $ARGUMENTS picked up again.

If no number was given, ask which ticket (`/taller:status` lists them).

1. Resume it:

   `taller --answers <answers file> ticket resume <number>`

   The answers file is `taller-answers-resume.json` in your temporary directory. If
   Taller prints `NEEDS <id>` (exit code 3), ask the owner that question in plain words,
   add `"<id>": "<answer>"` to the file, and run the same command again.

   If the ticket was stopped for a reason the owner has to deal with first (Taller
   prints it), tell them the reason in plain words and stop here.

2. Carry it on:

   `taller ticket run <number>`

   It can take many minutes: run it in the background and report when it finishes.

3. Tell the owner, plainly, where the ticket stopped and what comes next.
