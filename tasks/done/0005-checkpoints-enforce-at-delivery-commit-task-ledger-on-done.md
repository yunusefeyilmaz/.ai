---
id: 0005
title: "Checkpoints: enforce at delivery, commit task ledger on done"
status: done
owner: deep-seek-reviewer
priority: medium
spec: specs/done/0005-checkpoints-enforce-at-delivery-commit-task-ledger-on-done.md
depends_on: "0001, 0003"
scope_allowed: "lib/runtime/checkpoints.py, lib/tasks/workflow.py, lib/cmd/task.py, lib/cmd/checkpoint.py, lib/tests/test_checkpoint_gate.py"
scope_forbidden: null
locks: "lib/runtime/checkpoints.py, lib/tasks/workflow.py, lib/cmd/task.py, lib/cmd/checkpoint.py, lib/tests/test_checkpoint_gate.py"
branch: null
created: 2026-11-04T08:14:04Z
updated: 2026-11-06T07:54:01Z
lock: null
submitted_by: deep-seek
merged_into: develop
merged_at: 2026-11-06T07:53:39Z
reviewed_by: deep-seek-reviewer
reviewed_at: 2026-11-06T07:54:00Z
---

# 0005 - Checkpoints: enforce at delivery, commit task ledger on done

## Intent

`ai checkpoint` exists and `ai now` hints at it, but delivery never requires one, so a long task can be handed over with no recoverable state. `ai task done` also archives the task and spec without committing the ledger, leaving develop dirty for the next agent.

## Acceptance criteria

- [ ] A checkpoint is required at `ai task review` once the task has been claimed longer than the configured warn threshold, and the refusal names `ai checkpoint`
- [ ] A fresh task can still be delivered without a checkpoint (no busywork)
- [ ] Checkpoint output records real state: status, branch, HEAD, and next step, without unresolved HTML placeholders
- [ ] `ai task done` commits the archived task/spec/board changes so the working tree is clean afterwards
- [ ] Regression tests cover the required-checkpoint case, the fresh-task case, and the clean tree after done
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0005-checkpoints-enforce-at-delivery-commit-task-ledger-on-done.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-04T08:14:04Z | chief-1 | - -> todo | created
- 2026-11-06T06:50:01Z | deep-seek | todo -> in_progress | claimed
- 2026-11-06T06:50:03Z created branch feature/0005-checkpoints-enforce-at-delivery-commit-t from develop by deep-seek
- 2026-11-06T07:03:13Z committed: feat: enforce checkpoints at delivery and commit the done ledger
- 2026-11-06T07:06:36Z | deep-seek | in_progress -> review | submitted for independent review | check passed @6e9c2835 by deep-seek (tests passed, ruff passed, mypy passed)
- 2026-11-06T07:37:16Z | deep-seek-reviewer | review -> review | claimed
- 2026-11-06T07:50:37Z committed: chore(task): record review claim for 0005
- 2026-11-06T07:53:39Z merged feature/0005-checkpoints-enforce-at-delivery-commit-t into develop by deep-seek-reviewer
- 2026-11-06T07:54:01Z | deep-seek-reviewer | review -> done | approved | check passed @7e17f962 by deep-seek-reviewer (tests passed, ruff passed, mypy passed)
