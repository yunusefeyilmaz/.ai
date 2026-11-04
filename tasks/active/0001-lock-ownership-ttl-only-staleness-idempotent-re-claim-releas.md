---
id: 0001
title: "Lock ownership: TTL-only staleness, idempotent re-claim, release guard"
status: review
owner: reviewer-1
priority: high
spec: specs/active/0001-lock-ownership-ttl-only-staleness-idempotent-re-claim-releas.md
depends_on: null
scope_allowed: "lib/runtime/**, lib/cmd/lock.py, lib/cmd/recover.py, lib/cmd/doctor.py, lib/tests/test_lock_ownership.py"
scope_forbidden: null
locks: "lib/runtime/**, lib/cmd/lock.py, lib/cmd/recover.py, lib/cmd/doctor.py, lib/tests/test_lock_ownership.py"
branch: feature/0001-lock-ownership-ttl-only-staleness-idempo
created: 2026-11-04T08:14:03Z
updated: 2026-11-04T16:43:31Z
lock: task-0001
submitted_by: deepseek
---

# 0001 - Lock ownership: TTL-only staleness, idempotent re-claim, release guard

## Intent

A live claim becomes stale after 30s because PID liveness is consulted for task locks, so another agent can steal the task and `ai recover` can reset its owner. Re-claiming your own task fails, and `ai lock release` without --agent drops someone else's lock. Ownership must be the only thing that decides staleness.

## Acceptance criteria

- [ ] A task claimed by agent A stays A's after more than 30 seconds; a second agent's claim is refused and the branch/owner is unchanged
- [ ] ai doctor reports no stale lock for a live claim older than the PID liveness window
- [ ] ai recover proposes nothing for a live claim older than the PID liveness window
- [ ] Re-claiming the same task with the same agent succeeds, refreshes the lease, and does not duplicate locks
- [ ] ai lock release without --agent refuses with a message naming the current owner; --agent of another owner also refuses; --force still works
- [ ] Regression tests cover all four behaviors and pass
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0001-lock-ownership-ttl-only-staleness-idempotent-re-claim-releas.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-04T08:14:03Z | chief-1 | - -> todo | created
- 2026-11-04T08:15:15Z | impl-1 | todo -> in_progress | claimed
- 2026-11-04T08:15:16Z created branch feature/0001-lock-ownership-ttl-only-staleness-idempo from develop by impl-1
- 2026-11-04T08:19:47Z | impl-1 | in_progress -> todo | released
- 2026-11-04T15:29:00Z | deepseek | todo -> in_progress | claimed
- 2026-11-04T15:29:01Z created branch feature/0001-lock-ownership-ttl-only-staleness-idempo from develop by deepseek
- 2026-11-04T15:53:10Z checkpoint by deepseek (checkpoint, ?%)
- 2026-11-04T15:54:54Z committed: fix: make lock staleness ownership-based and guard release
- 2026-11-04T15:55:52Z checkpoint by deepseek (checkpoint, ?%)
- 2026-11-04T15:56:55Z | deepseek | in_progress -> review | submitted for independent review | check passed @79a69703 by deepseek (tests passed, ruff passed, mypy passed)
- 2026-11-04T16:16:32Z | reviewer-1 | review -> review | claimed
- 2026-11-04T16:43:31Z committed: chore: record 0001 review handover metadata
