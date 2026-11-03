---
status: draft
task: 0009
approved_by: null
approved_on: null
---

# Let task done inherit a stale task lock instead of refusing forever

## Intent

A crashed reviewer leaves a stale task lock; `ai task done` reads it raw and refuses, so the task is stuck in review even though claim and recover already treat the lock as stale.

## Behavior

### Changed

- A shared lease helper treats a stale task lock as unheld, while a corrupt lock still fails closed.
- `ai task done` uses that helper: a stale lock is replaced through `acquire_lock`, which already records the `lock_replaced_stale` event, so the reviewer can archive the task.
- Live foreign locks keep the current refusal, naming the holder.

### Preserved

- The reviewer claim requirement and the producer-never-approves rule are unchanged.
- The `done_gate` and role checks still run before any lock handling.
- Lock release and continuation cleanup after a successful archive are unchanged.

## Acceptance criteria

- [ ] `python lib/tests/run.py test_done_stale_lock` is green
- [ ] a stale task lock held by another agent is replaced and the task is archived
- [ ] a live lock held by another agent is still refused
- [ ] a corrupt task lock still fails closed
- [ ] the takeover is recorded in the event log
- [ ] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
