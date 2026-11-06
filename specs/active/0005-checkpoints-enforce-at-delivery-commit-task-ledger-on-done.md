---
status: draft
task: 0005
approved_by: null
approved_on: null
---

# Checkpoints: enforce at delivery, commit task ledger on done

## Intent

`ai checkpoint` exists and `ai now` hints at it, but delivery never requires one, so a long task can be handed over with no recoverable state. `ai task done` also archives the task and spec without committing the ledger, leaving develop dirty for the next agent.

## Behavior

### Changed

- `ai task review` requires a checkpoint when the task has been claimed longer than `handoff.warnAfterMinutes`; the refusal names the exact command.
- A task younger than the threshold can still be delivered without a checkpoint.
- The checkpoint writer fills status, branch, HEAD and next step automatically; unresolved template placeholders are replaced.
- `ai task done` commits the archived task, spec and board changes on the integration branch so the tree is clean afterwards.

### Preserved

- `ai checkpoint` stays optional outside the delivery gate.
- Handoff and resume semantics are unchanged.
- The metadata commit keeps the existing commit type/message conventions.

## Acceptance criteria

- [x] A checkpoint is required at `ai task review` once the task has been claimed longer than the configured warn threshold, and the refusal names `ai checkpoint`
- [x] A fresh task can still be delivered without a checkpoint (no busywork)
- [x] Checkpoint output records real state: status, branch, HEAD, and next step, without unresolved HTML placeholders
- [x] `ai task done` commits the archived task/spec/board changes so the working tree is clean afterwards
- [x] Regression tests cover the required-checkpoint case, the fresh-task case, and the clean tree after done
- [x] Tests cover the new behavior and pass

## Out of scope

- Time-based background checkpoints.
- Changing the checkpoint file format beyond auto-filled fields.

## Status

draft -> in progress -> shipped.
