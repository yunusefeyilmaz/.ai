---
id: 0008
title: "Share one evidence state machine between resume, review and status"
status: todo
owner: null
priority: high
spec: specs/active/0008-share-one-evidence-state-machine-between-resume-review-and-s.md
depends_on: null
scope_allowed: "lib/runtime/evidence.py, lib/runtime/checkpoints.py, lib/cmd/history.py, lib/tests/test_evidence_state.py"
scope_forbidden: null
locks: "lib/runtime/evidence.py, lib/runtime/checkpoints.py, lib/cmd/history.py, lib/tests/test_evidence_state.py"
created: 2026-11-03T07:45:14Z
updated: 2026-11-03T07:45:14Z
lock: null
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

## Log

- 2026-11-03T07:45:14Z | orchestrator | - -> todo | created
