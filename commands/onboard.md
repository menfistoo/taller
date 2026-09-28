---
description: Set Taller up, then create a new project with it or bring an existing repository in
argument-hint: new <name>, or adopt <path>
allowed-tools: Bash(taller setup:*), Bash(taller doctor:*), Bash(taller project new:*), Bash(taller project adopt:*), Bash(taller --answers:*)
---

The owner wants: $ARGUMENTS

If it is not clear whether they want a new project or to bring an existing repository
in, ask.

Every step below uses an answers file: `taller-answers-onboard.json` in your temporary
directory. When Taller prints `NEEDS <id>` and exits with code 3, it is asking the owner
something. Ask the owner that question in plain words - explain any term they may not
know, and offer the choices Taller listed - then add `"<id>": "<answer>"` to the file (a
list of strings when it asks for several lines) and run the same command again. Answers
are kept between runs, so repeating a command does not start over.

1. `taller doctor` shows whether Taller is set up. If it is not, run
   `taller --answers <answers file> setup` until it finishes.

2. For a new project:

   `taller --answers <answers file> project new <name> --no-open`

   For an existing repository:

   `taller --answers <answers file> project adopt <path> --no-open`

3. Taller shows a brief before it writes anything. Read it to the owner in plain words
   and let them approve it or change an answer; their choice is the `brief` answer.

4. When it finishes, tell the owner what was created and that `/taller:new` starts the
   first ticket.
