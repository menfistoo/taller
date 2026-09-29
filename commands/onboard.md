---
description: Set Taller up, then create a new project with it or bring an existing repository in
argument-hint: new <name>, or adopt <path>
allowed-tools: Bash(taller setup:*), Bash(taller doctor:*), Bash(taller project new:*), Bash(taller project adopt:*), Bash(taller answer:*)
---

The owner wants: $ARGUMENTS

If it is not clear whether they want a new project or to bring an existing repository
in, ask. For a new project, confirm with the owner where it should be created.

1. `taller doctor` shows whether Taller is set up. If it is not, run `taller setup`.

2. For a new project:

   `taller project new <name> --path <the folder it goes in> --no-open`

   For an existing repository:

   `taller project adopt <path> --no-open`

   Taller asks the onboarding questions one at a time. Explain any term the owner may
   not know, and offer the choices Taller lists. Taller shows a brief before it writes
   anything: read it to the owner in plain words and let them approve it or change an
   answer.

3. When Taller prints `NEEDS <id>` and exits with code 3, it needs an answer only the
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

4. When it finishes, tell the owner what was created and that `/taller:new` starts the
   first ticket.
