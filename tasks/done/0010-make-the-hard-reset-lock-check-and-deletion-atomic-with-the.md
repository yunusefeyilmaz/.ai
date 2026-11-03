---
id: 0010
title: "Make the hard-reset lock check and deletion atomic with the state mutex"
status: done
owner: null
priority: medium
spec: specs/done/0010-make-the-hard-reset-lock-check-and-deletion-atomic-with-the.md
depends_on: null
scope_allowed: "lib/cmd/reset.py, lib/tests/test_reset_mutex.py"
scope_forbidden: null
locks: "lib/cmd/reset.py, lib/tests/test_reset_mutex.py"
branch: null
created: 2026-11-03T07:45:14Z
updated: 2026-11-03T08:40:01Z
lock: null
submitted_by: buffy-impl
merged_into: develop
merged_at: 2026-11-03T08:40:01Z
reviewed_by: buffy-reviewer
reviewed_at: 2026-11-03T08:40:01Z
---

# 0010 - Make the hard-reset lock check and deletion atomic with the state mutex

## Intent

`ai reset --hard` re-checks locks and then deletes files outside the registry mutex, so a lock or state write can land between the check and the deletion.

## Acceptance criteria

- [ ] `python lib/tests/run.py test_reset_mutex` is green
- [ ] the final lock check and the file removal both run inside `registry_mutex()`
- [ ] `workspace_state_guard()` cannot observe a half-deleted workspace
- [ ] the project lock is released only after the mutex is released
- [ ] a filesystem failure still reports the partial cleanup and refreshes the board
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0010-make-the-hard-reset-lock-check-and-deletion-atomic-with-the.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T07:45:14Z | orchestrator | - -> todo | created
- 2026-11-03T08:32:23Z | buffy-impl | todo -> in_progress | claimed
- 2026-11-03T08:32:24Z created branch feature/0010-make-the-hard-reset-lock-check-and-delet from develop by buffy-impl
- 2026-11-03T08:38:22Z committed: fix: check locks and delete reset state under the registry mutex
- 2026-11-03T08:38:27Z | buffy-impl | in_progress -> review | submitted for independent review | check passed @66e381bd by buffy-impl (no commands)
- 2026-11-03T08:40:01Z merged feature/0010-make-the-hard-reset-lock-check-and-delet into develop by buffy-reviewer
- 2026-11-03T08:40:01Z | buffy-reviewer | review -> done | approved | check passed @4142fe29 by buffy-reviewer (no commands)
