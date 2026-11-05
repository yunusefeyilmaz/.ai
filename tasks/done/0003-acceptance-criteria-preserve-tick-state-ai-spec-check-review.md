---
id: 0003
title: "Acceptance criteria: preserve tick state, ai spec check, review gate, shipped spec"
status: done
owner: freebuff-reviewer
priority: high
spec: specs/done/0003-acceptance-criteria-preserve-tick-state-ai-spec-check-review.md
depends_on: null
scope_allowed: "ai.py, lib/specs/**, lib/tasks/lifecycle.py, lib/cmd/review.py, lib/cmd/spec.py, lib/cmd/task.py, lib/cmd/capabilities.py, lib/tests/test_acceptance_criteria.py, lib/tests/run.py"
scope_forbidden: null
locks: "ai.py, lib/specs/**, lib/tasks/lifecycle.py, lib/cmd/review.py, lib/cmd/spec.py, lib/cmd/task.py, lib/cmd/capabilities.py, lib/tests/test_acceptance_criteria.py, lib/tests/run.py"
branch: null
created: 2026-11-04T08:14:04Z
updated: 2026-11-05T15:00:47Z
lock: null
submitted_by: freebuff
merged_into: develop
merged_at: 2026-11-05T14:59:37Z
reviewed_by: freebuff-reviewer
reviewed_at: 2026-11-05T15:00:47Z
---

# 0003 - Acceptance criteria: preserve tick state, ai spec check, review gate, shipped spec

## Intent

Acceptance criteria are decorative: there is no command to tick them, the parser discards [x], ai review prints them without boxes, ai task review never reads them, and archived specs stay status: draft with every box empty. The product's core promise does not work.

## Acceptance criteria

Criteria live in the spec: `specs/active/0003-acceptance-criteria-preserve-tick-state-ai-spec-check-review.md`. Tick each one as it becomes true: `ai spec check 0003 <n>`.

## Plan

Spec: `specs/active/0003-acceptance-criteria-preserve-tick-state-ai-spec-check-review.md`

<!-- Filled by the planner. -->

## Notes

- 2026-11-05 freebuff: took over from opencode (its session stopped with the work uncommitted).
  Added `lib/cmd/capabilities.py` to scope/locks: the new `spec` command needed its one-line
  description, otherwise `test_capabilities` fails on the published contract.
- 2026-11-05 freebuff: added `lib/tests/run.py` to scope/locks with the user's approval and raised
  the per-module harness timeout 600s -> 900s. `test_field_report` passes alone (216s) but needs
  ~650s under `-j 8` on this machine; the suite wall time is 826s vs the 650s of the last green
  check, so the old cap now reads as a hang that is not there. Still a real hang detector.

## Log

- 2026-11-04T08:14:04Z | chief-1 | - -> todo | created
- 2026-11-05T09:52:50Z | opencode-1 | todo -> in_progress | claimed
- 2026-11-05T09:52:51Z | opencode-1 | in_progress -> todo | claim rolled back | the task branch could not start
- 2026-11-05T11:36:19Z | opencode | todo -> in_progress | claimed
- 2026-11-05T11:36:20Z created branch feature/0003-acceptance-criteria-preserve-tick-state from develop by opencode
- 2026-11-05T11:52:21Z | freebuff | in_progress -> in_progress | claimed
- 2026-11-05T11:52:21Z | freebuff | in_progress -> in_progress | claim rolled back | the task branch could not start
- 2026-11-05T11:53:15Z | freebuff | in_progress -> in_progress | claimed
- 2026-11-05T11:53:16Z switched to branch feature/0003-acceptance-criteria-preserve-tick-state from develop by freebuff
- 2026-11-05T12:30:33Z committed: feat: make acceptance criteria tickable state, gated at review, shipped on done
- 2026-11-05T12:51:44Z committed: chore: raise the per-module test timeout to 900s on this slower machine
- 2026-11-05T14:05:44Z checkpoint by freebuff (checkpoint, ?%)
- 2026-11-05T14:05:46Z committed: chore: tick all eight criteria and record the takeover notes
- 2026-11-05T14:08:54Z committed: chore: tick all eight criteria and record the takeover notes
- 2026-11-05T14:23:40Z | freebuff | in_progress -> review | submitted for independent review | check passed @41d1cae7 by freebuff (tests passed, ruff passed, mypy passed)
- 2026-11-05T14:25:03Z | freebuff-reviewer | review -> review | claimed
- 2026-11-05T14:48:58Z committed: chore: record the review claim before the merge
- 2026-11-05T14:59:37Z merged feature/0003-acceptance-criteria-preserve-tick-state into develop by freebuff-reviewer
- 2026-11-05T15:00:47Z | freebuff-reviewer | review -> done | approved | check passed @3e58f987 by freebuff-reviewer (tests passed, ruff passed, mypy passed)
