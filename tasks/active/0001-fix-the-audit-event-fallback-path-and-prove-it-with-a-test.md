---
id: 0001
title: "Fix the audit-event fallback path and prove it with a test"
status: in_progress
owner: implementer
priority: high
spec: specs/active/0001-fix-the-audit-event-fallback-path-and-prove-it-with-a-test.md
depends_on: null
scope_allowed: "lib/runtime/events.py, lib/tests/test_events_fallback.py"
scope_forbidden: null
locks: "lib/runtime/events.py, lib/tests/test_events_fallback.py"
branch: feature/0001-fix-the-audit-event-fallback-path-and-pr
created: 2026-11-03T07:17:31Z
updated: 2026-11-03T07:18:22Z
lock: task-0001
---

# 0001 - Fix the audit-event fallback path and prove it with a test

## Intent

The audit trail promises it is never completely empty, but the final fallback calls _write_event with an argument the function does not accept, so the write raises TypeError exactly when the ledger is already in trouble.

## Acceptance criteria

- [ ] `python lib/tests/run.py test_events_fallback` is green
- [ ] when both normal event writes fail, `append_event` returns without raising and prints a WARN to stderr
- [ ] the fallback record is still attempted and contains `_fallback: true`
- [ ] an unreadable/untouchable events file never makes a caller crash
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0001-fix-the-audit-event-fallback-path-and-prove-it-with-a-test.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T07:17:31Z | orchestrator | - -> todo | created
- 2026-11-03T07:17:43Z | implementer | todo -> in_progress | claimed
- 2026-11-03T07:17:44Z created branch feature/0001-fix-the-audit-event-fallback-path-and-pr from develop by implementer
- 2026-11-03T07:18:22Z committed: fix: make the audit-event fallback path safe
