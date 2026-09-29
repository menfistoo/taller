# Run the test suite on Linux in GitHub Actions

- Kind: feature
- Created: 2026-09-29T20:06:48

## In the owner's words

Run the test suite on Linux in GitHub Actions. The workflow adoption just wrote needs ci.taller_source set, and the suite has never run on anything but Windows: taller.cli's POSIX branches (ps instead of tasklist, start_new_session instead of CREATE_NEW_PROCESS_GROUP, the lock's delete-pending handling) have never been executed. Expect the first run to be red, and treat what it finds as the point of the ticket.
