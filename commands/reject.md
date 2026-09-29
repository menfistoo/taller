---
description: Reject a Taller ticket at its checkpoint, with the owner's reason, so the next attempt starts from it
argument-hint: the ticket number, then why
allowed-tools: Bash(taller ticket reject:*), Bash(taller answer:*)
---

The owner rejects: $ARGUMENTS

A rejection needs the owner's reason, in their words: the next attempt starts from it.
If the ticket number is missing, ask for it. Do not invent a reason or shorten the
owner's.

1. Reject it, and let Taller ask for the reason:

   `taller ticket reject <number>`

   Taller stops with `NEEDS ticket.reason`; record the owner's reason as below.

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

3. Tell the owner what happened: where the ticket went back to, and that the reason is
   kept with it. It does not run again until they say so (`/taller:resume` or
   `taller ticket run`).
