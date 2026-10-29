---
status: approved
task: 0004
approved_by: user
approved_on: 2026-10-29
---

# P1 value: workflow metrics ledger

## Intent

The workspace says it is better than a chat log, but it has no local evidence
to measure task flow. Record selected CLI lifecycle events in an append-only
local ledger and provide a read-only summary so teams can inspect completion
time, review time, retries, lock contention, resumes, and activity by agent.

## Behavior

### Changed

- Append one JSON object per event to `runtime/state/events.jsonl`. Each record
  has a UTC timestamp, event name, and relevant task, agent, or resource fields.
- At a UTC date change, rotate the prior active ledger to
  `runtime/state/events-YYYY-MM-DD.jsonl`; metrics reads the active file and
  all dated ledgers in timestamp order.
- Record task creation, claim, review submission, merge, completion, lock
  refusal, checkpoint, resume, and release events. Count retries as claims for
  a task after its first claim. Count resume activity from successful `resume`
  commands.
- Add `ai metrics [--json] [--since <date>]`. JSON reports completed task
  count, median creation-to-completion seconds, median review-to-merge seconds,
  lock refusals, retries, resumes, and per-agent event counts. `--since` filters
  by event timestamp while retaining earlier lifecycle events needed to
  calculate durations for matching completions or merges.
- Keep all records local under runtime state. Do not include task titles,
  message bodies, personal data, or network destinations in the ledger.

### Preserved

- Existing command results and state transitions remain unchanged.
- Missing or empty event ledgers produce zero-valued metrics without creating
  files when running `ai metrics`.
- The event ledger is operational data and may be cleared by the existing hard
  reset; no external service or dependency is introduced.

## Acceptance criteria

- [ ] Successful task creation, claim, review, merge, completion, checkpoint,
      and resume commands append one parseable JSON line per event; a refused
      lock acquisition appends one refusal event.
- [ ] The active ledger rotates on a UTC date change, preserving prior events
      in a dated file, and metrics aggregates across both files.
- [ ] `ai metrics --json` reports completed count, median creation-to-done and
      review-to-merge durations, refusal count, retries, resumes, and counts by
      agent; `--since` filters the reported period correctly.
- [ ] Reading metrics with no ledger is read-only and reports zero counts.
- [ ] A local lifecycle test asserts event records and exact reported values;
      the test is included in the fast `ai check` suite.
- [ ] `ai check --strict` passes.

## Out of scope

- Uploading metrics, tracking shell commands or task content, dashboards, and
  historical backfill from task files that predate the ledger.
- Changing task/lock/checkpoint semantics or adding third-party dependencies.

## Status

Approved by user on 2026-10-29. Implementation is ready for independent review.
