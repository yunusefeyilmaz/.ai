---
status: draft
task: 0001
approved_by: null
approved_on: null
---

# Fix the audit-event fallback path and prove it with a test

## Intent

The audit trail promises it is never completely empty, but the final fallback calls _write_event with an argument the function does not accept, so the write raises TypeError exactly when the ledger is already in trouble.

## Behavior

### Changed

<!-- What will be different. Be concrete. -->

### Preserved

<!-- What must not change. Explicitly list existing behavior at risk. -->

## Acceptance criteria

- [ ] `python lib/tests/run.py test_events_fallback` is green
- [ ] when both normal event writes fail, `append_event` returns without raising and prints a WARN to stderr
- [ ] the fallback record is still attempted and contains `_fallback: true`
- [ ] an unreadable/untouchable events file never makes a caller crash
- [ ] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
