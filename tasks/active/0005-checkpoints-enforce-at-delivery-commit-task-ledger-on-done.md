---
id: 0005
title: "Checkpoints: enforce at delivery, commit task ledger on done"
status: todo
owner: null
priority: medium
spec: specs/active/0005-checkpoints-enforce-at-delivery-commit-task-ledger-on-done.md
depends_on: "0001, 0003"
scope_allowed: "lib/runtime/checkpoints.py, lib/tasks/workflow.py, lib/cmd/task.py, lib/cmd/checkpoint.py, lib/tests/test_checkpoint_gate.py"
scope_forbidden: null
locks: "lib/runtime/checkpoints.py, lib/tasks/workflow.py, lib/cmd/task.py, lib/cmd/checkpoint.py, lib/tests/test_checkpoint_gate.py"
created: 2026-11-04T08:14:04Z
updated: 2026-11-04T08:14:04Z
lock: null
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
