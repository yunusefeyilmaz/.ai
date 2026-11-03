---
status: draft
task: 0010
approved_by: null
approved_on: null
---

# Make the hard-reset lock check and deletion atomic with the state mutex

## Intent

`ai reset --hard` re-checks locks and then deletes files outside the registry mutex, so a lock or state write can land between the check and the deletion.

## Behavior

### Changed

- `ai reset --hard` performs its final lock re-check, target validation and deletions while holding `registry_mutex()`.
- The project lock is released only after the mutex is released, so a concurrent state writer sees the reset lock and refuses instead of observing a half-deleted workspace.
- The board refresh and partial-failure reporting keep their current place relative to the deletion.

### Preserved

- The interactive confirmation, pre-flight lock check and error messages are unchanged.
- `ai reset` still refuses when a lock exists or the terminal is not interactive.
- The set of files a hard reset deletes does not change.

## Acceptance criteria

- [ ] `python lib/tests/run.py test_reset_mutex` is green
- [ ] the final lock check and the file removal both run inside `registry_mutex()`
- [ ] `workspace_state_guard()` cannot observe a half-deleted workspace
- [ ] the project lock is released only after the mutex is released
- [ ] a filesystem failure still reports the partial cleanup and refreshes the board
- [ ] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
