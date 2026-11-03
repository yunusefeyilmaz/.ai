---
status: draft
task: 0003
approved_by: null
approved_on: null
---

# Roll back a claim when the task branch cannot start

## Intent

A failed branch start currently leaves the task in_progress and holds its locks, so the next agent sees a task nobody can release without an operator escape hatch.

## Behavior

### Changed

<!-- What will be different. Be concrete. -->

### Preserved

<!-- What must not change. Explicitly list existing behavior at risk. -->

## Acceptance criteria

- [ ] `python lib/tests/run.py test_claim_rollback` is green
- [ ] when branch creation fails, `ai task claim` exits non-zero and the task returns to its previous status with owner/lock cleared
- [ ] the task lease and every declared file lock are released on rollback
- [ ] a rollback is recorded in task history and in the event log
- [ ] a successful claim still starts the branch and prints the claim exactly once
- [ ] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
