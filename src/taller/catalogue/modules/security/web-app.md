> Security rules for a web application with several users and more than one level of access.

This applies when more than one person signs in and they are not all equally
entitled. Every rule below has been the direct cause of a real breach in some
application, which is why it is stated as an absolute rather than a preference.

## Authentication is not authorisation

**Every non-public route needs two checks: who is this, and may they do this.**
Authentication alone answers the first question only, so a route that merely
requires a session lets any signed-in user reach it. The overwhelming majority of
access-control failures in web applications are exactly this: a route that checked
the session and forgot the permission.

**Check the permission against the record, not against the request.** A user who may
edit their own records must be checked against the owner of the record identified by
the request, not against the identifier the request supplied. Anything taken from
the URL, a form field or a hidden input is under the caller's control.

**Deny by default.** A new route is inaccessible until it says who may use it. If
the default is open, the failure mode of forgetting is exposure; if the default is
closed, the failure mode is a visible error that gets fixed in minutes.

## Forms, queries and secrets

**Every state-changing form carries a CSRF token, and the server rejects the request
without it.** Otherwise another site can make the user's own browser submit that
form with the user's own session.

**SQL parameters are always bound.** Never build a query by formatting or
concatenating a value into it, not even a value that "can only be a number", and not
even in code only an administrator can reach: the type is not guaranteed and the
administrator path is the most valuable one to compromise.

**Secrets come from the environment.** Keys, tokens, passwords and signing secrets
are read at startup from the environment and never appear in the repository, in a
default value, in a log line or in an error page. A secret in version control stays
compromised after it is deleted, because the history keeps it.

## Transactions and the audit trail

**A read-then-write is one transaction.** Checking a balance, a stock level or a
permission and then writing based on what you read is a single atomic operation, or
it is a race that two simultaneous requests will win together.

**Log anything touching money, permissions or deletion:** who, when, what changed,
and from what to what. These are the three areas where you will one day have to
answer a question about the past, and the answer either exists in an append-only
record or it does not exist at all.
