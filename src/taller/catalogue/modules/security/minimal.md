> Security rules for a single-operator tool with no sign-in, and when they stop being enough.

This applies to a program run by the person who owns it: a local tool, a helper
script, a page with no accounts. There is no login, so there is nothing to bypass.
That removes access control from the picture and removes nothing else.

## Secrets

**Secrets come from the environment or from a file outside the repository.** Not from
a constant, not from a default argument, not from a comment saying it is only for
testing. A single operator still pushes to a remote, still shares a screenshot, and
still publishes the repository some day. A secret in the history stays compromised
after the line is deleted, so the cost of the mistake is not proportional to the
size of the project.

**Nothing secret is printed.** Keys and tokens do not belong in log output or in an
error message, because logs get pasted into issues and chat when something breaks.

## Input is untrusted even when it is yours

The operator is trusted; the data is not. A file downloaded from somewhere, a
response from an API, a spreadsheet exported by another program - all of it is input
written by someone else, and it arrives malformed eventually.

**Never pass input into a shell.** Call programs with an argument list, never by
building a command string, so a value containing a semicolon or a quote cannot
become another command. Never evaluate input as code, and never deserialise it with
a format that can construct arbitrary objects; use JSON or CSV.

**Validate before use, and fail loudly.** A value that is wrong should stop the run
with a message naming the file and the field. Silently coercing it is how a bad
input becomes a bad output that nobody notices for weeks.

## Paths

**Every path built from input is resolved and checked to be inside the directory it
belongs to.** A name like `../../etc/passwd` or an absolute path arriving in a field
is the whole of path traversal, and it does not require a hostile user - an archive
or a data file written by another tool is enough. Resolve the candidate, resolve the
intended parent, and confirm the first is under the second before opening it.

## When this module is no longer the right one

Switch to the multi-user security module the moment any of these becomes true:

- More than one person signs in, or will.
- Two people using it should see different data, or have different rights.
- It becomes reachable from a network the operator does not control.
- It stores anything about a third party who is not the operator.

These are not gradual. On the day one of them is true, the rules this module leaves
out - authentication, a permission check per route, CSRF, an audit trail - are all
missing at once, and the application was built without room for them.
