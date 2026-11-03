---
id: 0003
title: "Roll back a claim when the task branch cannot start"
status: in_progress
owner: implementer
priority: high
spec: specs/active/0003-roll-back-a-claim-when-the-task-branch-cannot-start.md
depends_on: "0001, 0002"
scope_allowed: "lib/cmd/task.py, lib/tasks/lifecycle.py, lib/tests/test_claim_rollback.py"
scope_forbidden: null
locks: "lib/cmd/task.py, lib/tasks/lifecycle.py, lib/tests/test_claim_rollback.py"
branch: feature/0003-roll-back-a-claim-when-the-task-branch-c
created: 2026-11-03T07:17:31Z
updated: 2026-11-03T07:23:23Z
lock: task-0003
---

# 0003 - Roll back a claim when the task branch cannot start

## Intent

A failed branch start currently leaves the task in_progress and holds its locks, so the next agent sees a task nobody can release without an operator escape hatch.

## Acceptance criteria

- [ ] `python lib/tests/run.py test_claim_rollback` is green
- [ ] when branch creation fails, `ai task claim` exits non-zero and the task returns to its previous status with owner/lock cleared
- [ ] the task lease and every declared file lock are released on rollback
- [ ] a rollback is recorded in task history and in the event log
- [ ] a successful claim still starts the branch and prints the claim exactly once
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0003-roll-back-a-claim-when-the-task-branch-cannot-start.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T07:17:31Z | orchestrator | - -> todo | created
- 2026-11-03T07:20:48Z | implementer | todo -> in_progress | claimed
- 2026-11-03T07:20:49Z created branch feature/0003-roll-back-a-claim-when-the-task-branch-c from develop by implementer
- 2026-11-03T07:23:23Z committed: fix: roll back a claim when the branch cannot start
