> Prohibitions that hold in every stack, whatever the ticket says and whoever is asking.

Each rule below is here because breaking it destroys something that cannot be
restored by the next commit: a leaked secret, lost data, or the credibility of the
test suite. They are not stylistic. A ticket that appears to require one of them is a
ticket to stop and ask about.

## Never commit a secret

No key, token, password or connection string with credentials in it, ever, in any
file, including a test fixture, a comment, an example configuration and a commit
message. Deleting the line later does not help: the value lives in the history, the
history is pushed, and the only real remedy is rotating the secret. If a secret has
already been committed, say so immediately - the rotation is the fix, and its cost
grows with every hour nobody knows.

## Never weaken a check to make it pass

Not a test, not a linter rule, not a type check, not a gate threshold. A failing
check is information; relaxing it deletes the information and keeps the defect. If
the check is genuinely wrong, that is a separate, argued change with its reason
recorded - not a value quietly edited in the same commit as the code it was blocking.

## Never edit a test to match broken behaviour

A test asserts what was intended. Changing the assertion because the code now does
something else converts a caught regression into documented behaviour, and the next
person has no way to tell which is which. Fix the code. If the intent really has
changed, change the test in its own commit, with the reason stated in the message.

## Never delete data to resolve an error

Not a row, not a table, not a file, not a migration, not a branch. Dropping and
recreating is not a repair, it is a repair with the evidence destroyed, and it is
irreversible in exactly the cases where it seemed easiest. Reproduce the error
against a copy. If data really must go, that is the owner's decision, made with a
backup in hand.

## Never leave a failing check disabled

A skipped test, a commented-out assertion, a suppressed rule with no reason and a
disabled job all report success while checking nothing, which is worse than a red
build because it is quiet. Disable a check only with a recorded reason and the
condition for re-enabling it, and never as the last step before calling work done.

## Never bypass review because a change is small

Size does not predict risk: one character in a condition, a permission default, a
path or a comparison operator is the shape most serious defects arrive in. Review is
also the only record of why a change was made. Small changes are cheap to review, so
the argument for skipping it is never about cost.
