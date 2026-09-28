---
description: Reject a Taller ticket at its checkpoint, with the owner's reason, so the next attempt starts from it
argument-hint: the ticket number, then why
allowed-tools: Bash(taller ticket reject:*), Bash(taller --answers:*)
---

The owner rejects: $ARGUMENTS

A rejection needs the owner's reason, in their words: the next attempt starts from it.
If the ticket number or the reason is missing, ask for it. Do not invent a reason or
shorten the owner's.

1. Reject it:

   `taller --answers <answers file> ticket reject <number> --reason "<the owner's reason>"`

   The answers file is `taller-answers-reject.json` in your temporary directory. If
   Taller prints `NEEDS <id>` (exit code 3), ask the owner that question in plain words,
   add `"<id>": "<answer>"` to the file, and run the same command again.

2. Tell the owner what happened: where the ticket went back to, and that the reason is
   kept with it. It does not run again until they say so (`/taller:resume` or
   `taller ticket run`).
