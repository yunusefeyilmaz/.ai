---
id: 0004
title: "P1 value: workflow metrics ledger"
status: todo
owner: null
priority: medium
spec: null
created: 2026-10-29T06:55:08Z
updated: 2026-10-29T06:55:08Z
lock: null
depends_on: 0003
---

# 0004 - P1 value: workflow metrics ledger

## Intent

"Better than a chat log" is currently an assertion. Measure the workflow so the
claim can be supported or rejected with data from real tasks.

## Acceptance criteria

- [ ] CLI state changes append one JSON line per event to
      `runtime/state/events.jsonl` (task created, claimed, reviewed, done;
      lock refused; checkpoint; resume).
- [ ] `ai metrics [--json] [--since <date>]` reports tasks completed, median
      creation-to-done time, review-to-merge time, lock refusals, retries,
      resumes and per-agent counts.
- [ ] Metrics are derived only from committed/local state and never upload
      anything.
- [ ] A test records a short task lifecycle and asserts the reported numbers.

## Plan

1. Add a tiny append-only event writer with rotation-by-date.
2. Emit events from the existing command handlers.
3. Aggregate in one read-only command; document the limits of the sample.

## Notes

## Log

- 2026-10-29T06:55:08Z created
