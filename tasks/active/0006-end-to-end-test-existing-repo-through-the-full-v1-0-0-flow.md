---
id: 0006
title: "End-to-end test: existing repo through the full v1.0.0 flow"
status: in_progress
owner: deep-seek
priority: high
spec: specs/active/0006-end-to-end-test-existing-repo-through-the-full-v1-0-0-flow.md
depends_on: "0001, 0002, 0003, 0005, 0004"
scope_allowed: lib/tests/test_e2e_flow.py
scope_forbidden: null
locks: lib/tests/test_e2e_flow.py
branch: feature/0006-end-to-end-test-existing-repo-through-th
created: 2026-11-04T08:14:04Z
updated: 2026-11-06T08:36:47Z
lock: task-0006
---

# 0006 - End-to-end test: existing repo through the full v1.0.0 flow

## Intent

No test covers an existing Git repo end to end, which is why onboarding, the check gate and the criteria gate all regressed silently. One flow test locks them together.

## Acceptance criteria

- [ ] One test builds an existing Git repo, runs adopt, setup, plan, claim, checkpoint, criterion ticks, commit, check, review, finish and done
- [ ] The test asserts HEAD is develop after setup, the tree is clean after done, the checks really ran, and the spec is archived as shipped with all criteria ticked
- [ ] The test asserts review is refused while a criterion is unticked (negative case)
- [ ] The test runs green on the CI matrix
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0006-end-to-end-test-existing-repo-through-the-full-v1-0-0-flow.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-04T08:14:04Z | chief-1 | - -> todo | created
- 2026-11-06T08:08:03Z | deep-seek | todo -> in_progress | claimed
- 2026-11-06T08:08:05Z created branch feature/0006-end-to-end-test-existing-repo-through-th from develop by deep-seek
- 2026-11-06T08:35:29Z checkpoint by deep-seek (checkpoint, ?%)
- 2026-11-06T08:36:47Z committed: test: add existing-repo end-to-end flow test
