---
id: 0003
title: "Acceptance criteria: preserve tick state, ai spec check, review gate, shipped spec"
status: todo
owner: null
priority: high
spec: specs/active/0003-acceptance-criteria-preserve-tick-state-ai-spec-check-review.md
depends_on: null
scope_allowed: "ai.py, lib/specs/**, lib/tasks/lifecycle.py, lib/cmd/review.py, lib/cmd/spec.py, lib/cmd/task.py, lib/tests/test_acceptance_criteria.py"
scope_forbidden: null
locks: "ai.py, lib/specs/**, lib/tasks/lifecycle.py, lib/cmd/review.py, lib/cmd/spec.py, lib/cmd/task.py, lib/tests/test_acceptance_criteria.py"
created: 2026-11-04T08:14:04Z
updated: 2026-11-04T08:14:04Z
lock: null
---

# 0003 - Acceptance criteria: preserve tick state, ai spec check, review gate, shipped spec

## Intent

Acceptance criteria are decorative: there is no command to tick them, the parser discards [x], ai review prints them without boxes, ai task review never reads them, and archived specs stay status: draft with every box empty. The product's core promise does not work.

## Acceptance criteria

- [ ] The spec parser preserves per-criterion ticked state instead of stripping [ ]/[x]
- [ ] `ai spec check <id> <n>` ticks a criterion and `ai spec show <id>` prints each criterion with its box and a done/total count
- [ ] `ai task review` refuses while any real (non-generated) criterion is unticked and names the unticked ones
- [ ] `ai review` prints criteria as [x]/[ ] with progress, and Evidence/Checklist state reflects the spec instead of a hardcoded empty box
- [ ] `ai task done` sets the archived spec to status: shipped
- [ ] The duplicate acceptance list in the task body no longer competes with the spec (single source of truth, task body points at the spec)
- [ ] Regression tests cover ticking, the review refusal, and the archived status
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0003-acceptance-criteria-preserve-tick-state-ai-spec-check-review.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-04T08:14:04Z | chief-1 | - -> todo | created
