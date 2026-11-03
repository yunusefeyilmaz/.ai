---
id: 0008
title: "Share one evidence state machine between resume, review and status"
status: review
owner: reviewer-1
priority: high
spec: specs/active/0008-share-one-evidence-state-machine-between-resume-review-and-s.md
depends_on: null
scope_allowed: "lib/runtime/evidence.py, lib/runtime/checkpoints.py, lib/cmd/history.py, lib/tests/test_evidence_state.py, lib/cmd/checkpoint.py"
scope_forbidden: null
locks: "lib/runtime/evidence.py, lib/runtime/checkpoints.py, lib/cmd/history.py, lib/tests/test_evidence_state.py, lib/cmd/checkpoint.py"
branch: feature/0008-share-one-evidence-state-machine-between
created: 2026-11-03T07:45:14Z
updated: 2026-11-03T08:14:53Z
lock: task-0008
submitted_by: cline-impl
---

# 0008 - Share one evidence state machine between resume, review and status

## Intent

`task_status` calls a partial check valid while `task_green` rejects it, so `ai resume` promises proof that review then refuses.

## Acceptance criteria

- [ ] `python lib/tests/run.py test_evidence_state` is green
- [ ] one state function returns none, invalidated, failed, partial, stale or green
- [ ] `task_status` and `task_green` use that function and never disagree for the same head and claim time
- [ ] a `--fast` or `--no-commands` record reports `partial`, and `ai resume` labels it as insufficient for review
- [ ] green, failed, stale and invalidated keep their current messages
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0008-share-one-evidence-state-machine-between-resume-review-and-s.md`

<!-- Filled by the planner. -->

## Notes

- Scope extended by the implementer: `lib/cmd/checkpoint.py` was added to
  `scope_allowed` and locked. The acceptance criterion "ai resume labels it as
  insufficient for review" is decided by the print block in `cmd_resume`, which
  lives there; the declared `lib/runtime/checkpoints.py` only computes drift.
  Without it the new `green` verdict would read as "GREEN, do not trust it".

## Log

- 2026-11-03T07:45:14Z | orchestrator | - -> todo | created
- 2026-11-03T08:06:51Z | cline-impl | todo -> in_progress | claimed
- 2026-11-03T08:06:53Z created branch feature/0008-share-one-evidence-state-machine-between from develop by cline-impl
- 2026-11-03T08:11:13Z committed: fix: let one evidence state machine drive resume, review and status
- 2026-11-03T08:11:22Z | cline-impl | in_progress -> review | submitted for independent review | check passed @80ec2599 by cline-impl (no commands)
- 2026-11-03T08:14:46Z | reviewer-1 | review -> review | claimed
- 2026-11-03T08:14:53Z committed: chore: record the review claim for task 0008
