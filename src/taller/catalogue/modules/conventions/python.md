> Python naming, module layout, error handling and comment rules for this codebase.

## Naming

`snake_case` for functions, variables and modules; `PascalCase` for classes;
`UPPER_SNAKE` for module-level constants. A leading underscore means "not part of
this module's interface" and is the only visibility marker used.

Names say what a thing is, not what type it has: `pending_orders`, not `order_list`.
Booleans read as assertions: `is_active`, `has_expired`. A function that performs an
action is a verb phrase; a function that answers a question is a noun or an
assertion, and does not also change state. Abbreviate nothing that is not already an
abbreviation everywhere else.

Short names are correct in short scopes. A comprehension variable may be one letter;
a module-level constant may not.

## Structure

One module has one subject, and its name says which. Functions do one thing at one
level of abstraction: a function that opens a file, parses it, validates it and
writes a report is four functions, and only the parsing one is testable on its own.

Imports are standard library, then third party, then local, each group separated by a
blank line and sorted. Never use a wildcard import: it makes the origin of a name
unanswerable without running the code.

A module does nothing at import time except define things. Work performed at import
time runs during test collection and during tooling that merely inspects the module,
in an order nobody chose.

## Error handling

**Never catch an exception you are not going to handle.** A bare `except` that logs
and continues converts a crash you would have fixed into wrong output you will not
notice. If there is nothing sensible to do, let it propagate.

**Catch the narrowest type, around the narrowest block.** A wide `try` hides which
statement failed, and the next person widens the catch rather than narrowing the
block.

**Raise with a message that names the input.** "Invalid value" costs an hour;
"expected an integer for `timeout_s`, got 'soon'" costs nothing. Use the project's
own exception types at its boundaries so a caller can distinguish a failure of this
code from a failure of the library underneath.

## Comments

**Comments explain why, never what.** The code already says what it does, and a
comment restating it becomes a lie the first time the code changes. Comment the
non-obvious decision: the constraint that forced this approach, the alternative that
failed, the bug this line prevents. A rule whose reason is written down survives
contact with a situation its author did not foresee; one without a reason gets
deleted by the first person it inconveniences.

Docstrings say what a function is for and what it guarantees, not how it works.
