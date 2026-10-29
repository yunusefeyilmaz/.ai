---
id: 0004
title: "P1 value: workflow metrics ledger"
status: in_progress
owner: codex
priority: medium
spec: specs/active/0004-p1-value-workflow-metrics-ledger.md
created: 2026-10-29T06:55:08Z
updated: 2026-10-29T08:25:22Z
lock: task-0004
depends_on: 0003
branch: feature/0004-p1-value-workflow-metrics-ledger
---

# 0004 - P1 value: workflow metrics ledger

## Intent

"Better than a chat log" is currently an assertion. Measure the workflow so the
claim can be supported or rejected with data from real tasks.

## Acceptance criteria

- [x] Task creation, claim, review, merge, completion, lock refusal,
      checkpoint, and resume events append JSONL records; the active ledger
      rotates by UTC date and metrics reads dated archives.
- [x] `ai metrics [--json] [--since <date>]` reports completions, median
      creation-to-done and review-to-merge seconds, refusals, retries, resumes,
      and per-agent event counts; period filtering retains earlier lifecycle
      events needed for durations.
- [x] Metrics stay local and the empty-ledger query does not create state.
- [x] Isolated lifecycle and rotation tests assert event records and metrics.
- [x] `ai check --strict` passes.

## Plan

1. Add a tiny append-only event writer with rotation-by-date.
2. Emit events from the existing command handlers.
3. Aggregate in one read-only command; document the limits of the sample.

Spec and plan approved by user on 2026-10-29.

## Notes

## Log

- 2026-10-29T06:55:08Z created
- 2026-10-29T08:15:04Z claimed by codex
- 2026-10-29T08:15:05Z created branch feature/0004-p1-value-workflow-metrics-ledger from develop by codex
- 2026-10-29 implementation ready: `ai check --strict` -> 35 tests passed in 51.9 seconds; 0 errors, 0 warnings.
- 2026-10-29T08:25:22Z committed: feat(metrics): record local workflow metrics
