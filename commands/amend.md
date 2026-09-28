---
description: Change one of Taller's rules - for every project that shares it, or for this project only - and refresh what it reaches
argument-hint: the rule to change, in the owner's words
allowed-tools: Bash(taller amend:*), Bash(taller answer:*)
---

The owner wants a rule changed: $ARGUMENTS

A rule that is wrong is changed, never argued around at review. Work it out with the
owner first:

1. Find the rule. Shared rules live in the hub (`~/.taller`): `modules/<area>/<name>.md`
   and `brands/<name>/`. A rule for this project only lives in its
   `.taller/constitution/` folder. Never edit `.taller/constitution/00-index.md` or
   `.taller/resolved.json`: Taller generates them.

2. Show the owner the current wording, agree the new wording with them, and say which
   projects share the rule if it is a hub one. Then edit the file.

3. Record it, and let Taller ask for the owner's reason:

   `taller amend`

   Add `--path <project>` for a rule in a project other than the one the chat is
   standing in. Taller stops with `NEEDS amend.reason`; record the reason as below.

4. When Taller prints `NEEDS <id>` and exits with code 3, it needs an answer only the
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

5. Tell the owner which projects Taller refreshed.
