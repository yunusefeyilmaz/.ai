---
status: draft
task: 0002
approved_by: null
approved_on: null
---

# Support nine-digit task ids from one constant

## Intent

normalize_id rejects anything over four digits even though the regex and doctor text promise nine, so task 10000 breaks every lookup and the error message points at the wrong rule.

## Behavior

### Changed

<!-- What will be different. Be concrete. -->

### Preserved

<!-- What must not change. Explicitly list existing behavior at risk. -->

## Acceptance criteria

- [ ] `python lib/tests/run.py test_task_ids` is green
- [ ] `normalize_id('10000')` returns '10000' and `normalize_id('123456789')` is accepted
- [ ] `normalize_id('1234567890')` is rejected with an error naming the nine-digit limit
- [ ] the limit lives in one exported constant and health/doctor wording is derived from it
- [ ] spec lookup by numeric id also accepts five or more digits
- [ ] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
