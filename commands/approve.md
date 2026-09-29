---
description: Approve a Taller ticket at the checkpoint it is waiting at, then let Taller's team carry on
argument-hint: the ticket number
allowed-tools: Bash(taller ticket approve:*), Bash(taller ticket run:*), Bash(taller answer:*)
---

The owner approves ticket $ARGUMENTS.

Only the owner approves. If no ticket number was given, ask which ticket they mean
(`/taller:status` lists them); never pick one yourself.

1. Approve it:

   `taller ticket approve <number>`

2. When Taller prints `NEEDS <id>` and exits with code 3, it needs an answer only the
   owner can give. Ask the owner the question it printed, in plain words, then record
   their answer and run the same command again:

   `taller answer <id> "<the answer>"`

   (one quoted argument per line when the question asks for several lines). Taller
   keeps these answers for this one command and forgets them when it finishes. If it
   says the question comes again in this run, record the owner's answer for this time
   the same way.

   If Taller says it is busy because another process is still working (usually a ticket
   run in the background), wait for that run to finish, then try again. Never remove or
   edit Taller's lock files.

3. Then carry the ticket on:

   `taller ticket run <number>`

   It can take many minutes: run it in the background and report when it finishes.

4. Tell the owner, plainly, where the ticket stopped and what comes next. If Taller says
   a branch must be merged first, say so; do not merge it yourself.
