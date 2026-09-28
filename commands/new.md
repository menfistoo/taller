---
description: Start a Taller ticket from what the owner asks for, then let Taller's team carry it to the next point that needs the owner
argument-hint: what should be done, in the owner's own words
allowed-tools: Bash(taller ticket new:*), Bash(taller ticket run:*), Bash(taller --answers:*)
---

The owner wants this done: $ARGUMENTS

If that is empty, ask the owner what should be done, in their own words, before going on.

1. Create the ticket, in the project the chat is standing in:

   `taller --answers <answers file> ticket new <the owner's words>`

   The answers file is a JSON file named `taller-answers-new.json` in your temporary
   directory. It may not exist yet; that is fine.

2. If Taller prints `NEEDS <id>` and exits with code 3, it needs an answer it cannot get
   by itself. Ask the owner the question Taller printed, in plain words. Add the answer
   to the answers file as `"<id>": "<answer>"` (a list of strings when the question asks
   for several lines), and run the same command again. Repeat until it finishes.

3. Note the ticket number Taller prints. Then start Taller's team on it:

   `taller ticket run <number>`

   This can take many minutes: run it in the background, tell the owner it has started,
   and report when it finishes.

4. Tell the owner, in a few plain sentences, where the ticket stopped and what they are
   asked to do next (usually: look at it, then `/taller:approve` or `/taller:reject`).
   Do not approve anything yourself.
