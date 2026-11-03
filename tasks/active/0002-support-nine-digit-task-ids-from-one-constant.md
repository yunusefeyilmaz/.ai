---
id: 0002
title: "Support nine-digit task ids from one constant"
status: todo
owner: null
priority: high
spec: specs/active/0002-support-nine-digit-task-ids-from-one-constant.md
depends_on: null
scope_allowed: "lib/core/fsio.py, lib/runtime/health.py, lib/specs/spec.py, lib/tests/test_task_ids.py"
scope_forbidden: null
locks: "lib/core/fsio.py, lib/runtime/health.py, lib/specs/spec.py, lib/tests/test_task_ids.py"
created: 2026-11-03T07:17:31Z
updated: 2026-11-03T07:17:31Z
lock: null
---

# 0002 - Support nine-digit task ids from one constant

## Intent

normalize_id rejects anything over four digits even though the regex and doctor text promise nine, so task 10000 breaks every lookup and the error message points at the wrong rule.

## Acceptance criteria

- [ ] `python lib/tests/run.py test_task_ids` is green
- [ ] `normalize_id('10000')` returns '10000' and `normalize_id('123456789')` is accepted
- [ ] `normalize_id('1234567890')` is rejected with an error naming the nine-digit limit
- [ ] the limit lives in one exported constant and health/doctor wording is derived from it
- [ ] spec lookup by numeric id also accepts five or more digits
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0002-support-nine-digit-task-ids-from-one-constant.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T07:17:31Z | orchestrator | - -> todo | created
