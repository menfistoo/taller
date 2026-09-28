---
description: Show where the project's Taller tickets stand, or everything about one ticket
argument-hint: optionally, a ticket number
allowed-tools: Bash(taller ticket list:*), Bash(taller ticket show:*), Bash(taller answer:*)
---

The owner asks about: $ARGUMENTS

1. With no ticket number, list the open tickets:

   `taller ticket list`

   With a number, show that ticket:

   `taller ticket show <number>`

   These normally ask nothing.

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

3. Summarise it in plain words: what each ticket is, where it stands, and which ones
   are waiting for the owner. Say what the owner can do next, as slash commands
   (`/taller:approve <n>`, `/taller:reject <n>`, `/taller:resume <n>`).
