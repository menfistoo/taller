---
description: Change one of Taller's rules - for every project that shares it, or for this project only - and refresh what it reaches
argument-hint: the rule to change, in the owner's words
allowed-tools: Bash(taller amend:*), Bash(taller --answers:*)
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

3. Record it:

   `taller --answers <answers file> amend --reason "<the owner's reason, in their words>"`

   Add `--path <project>` for a rule in a project other than the one the chat is
   standing in. The answers file is `taller-answers-amend.json` in your temporary
   directory. If Taller prints `NEEDS <id>` (exit code 3), ask the owner that question in
   plain words, add `"<id>": "<answer>"` to the file, and run the same command again.

4. Tell the owner which projects Taller refreshed.
