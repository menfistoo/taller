---
description: Start a Taller ticket from what the owner asks for, then let Taller's team carry it to the next point that needs the owner
argument-hint: what should be done, in the owner's own words
allowed-tools: Bash(taller ticket new:*), Bash(taller ticket run:*), Bash(taller ticket list:*), Bash(taller answer:*)
---

The owner wants this done: $ARGUMENTS

If that is empty, ask the owner what should be done, in their own words, before going on.

1. Create the ticket, in the project the chat is standing in:

   `taller ticket new <the owner's words>`

   Taller's chief reads the words first, which can take a few minutes: give the command
   a long timeout. If it timed out or was interrupted, never run it again blindly - run
   `taller ticket list` first: the ticket may already exist, and a second run would make
   a second one.

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

3. Note the ticket number Taller prints. Then start Taller's team on it:

   `taller ticket run <number>`

   This can take many minutes: run it in the background, tell the owner it has started,
   and report when it finishes.

4. Tell the owner, in a few plain sentences, where the ticket stopped and what they are
   asked to do next (usually: look at it, then `/taller:approve` or `/taller:reject`).
   Do not approve anything yourself.
