---
id: 0009
title: "Let task done inherit a stale task lock instead of refusing forever"
status: done
owner: buffy-reviewer
priority: medium
spec: specs/done/0009-let-task-done-inherit-a-stale-task-lock-instead-of-refusing.md
depends_on: null
scope_allowed: "lib/cmd/task.py, lib/runtime/leases.py, lib/tests/test_done_stale_lock.py, lib/tests/test_workflow.py"
scope_forbidden: null
locks: "lib/cmd/task.py, lib/runtime/leases.py, lib/tests/test_done_stale_lock.py, lib/tests/test_workflow.py"
branch: feature/0009-let-task-done-inherit-a-stale-task-lock
created: 2026-11-03T07:45:14Z
updated: 2026-11-03T08:29:56Z
lock: null
submitted_by: cline-impl
reviewed_by: buffy-reviewer
reviewed_at: 2026-11-03T08:29:56Z
---

# 0009 - Let task done inherit a stale task lock instead of refusing forever

## Intent

A crashed reviewer leaves a stale task lock; `ai task done` reads it raw and refuses, so the task is stuck in review even though claim and recover already treat the lock as stale.

## Acceptance criteria

- [ ] `python lib/tests/run.py test_done_stale_lock` is green
- [ ] a stale task lock held by another agent is replaced and the task is archived
- [ ] a live lock held by another agent is still refused
- [ ] a corrupt task lock still fails closed
- [ ] the takeover is recorded in the event log
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0009-let-task-done-inherit-a-stale-task-lock-instead-of-refusing.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T07:45:14Z | orchestrator | - -> todo | created
- 2026-11-03T08:17:07Z | cline-impl | todo -> in_progress | claimed
- 2026-11-03T08:17:09Z created branch feature/0009-let-task-done-inherit-a-stale-task-lock from develop by cline-impl
- 2026-11-03T08:21:02Z committed: fix: let task done inherit a stale task lock instead of refusing
- 2026-11-03T08:21:08Z | cline-impl | in_progress -> review | submitted for independent review | check passed @b021ace4 by cline-impl (no commands)
- 2026-11-03T08:27:22Z | buffy-reviewer | review -> review | claimed
- 2026-11-03T08:29:56Z | buffy-reviewer | review -> done | approved | check failed @b021ace4 by buffy-reviewer (no commands)
