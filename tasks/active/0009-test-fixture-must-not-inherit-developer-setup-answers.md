---
id: 0009
title: "'Test fixture must not inherit developer setup answers'"
status: in_progress
owner: evren-deep-seek
priority: high
spec: specs/active/0009-test-fixture-must-not-inherit-developer-setup-answers.md
depends_on: null
scope_allowed: "lib/tests/**"
scope_forbidden: null
locks: "lib/tests/**"
branch: feature/0009-test-fixture-must-not-inherit-developer
created: 2026-11-04T08:19:47Z
updated: 2026-11-05T17:24:35Z
lock: task-0009
---

# 0009 - Test fixture must not inherit developer setup answers

## Intent

<!-- What problem does this solve? Who is it for? -->

## Acceptance criteria

- [ ] Every test fixture pins `workflow.requireCheck` to "strict" instead of inheriting the developer's `ai setup` answer
- [ ] A regression test copies a config with `requireCheck: true` and asserts the fixture workspace does not require checks in lite mode
- [ ] The existing suite passes after `ai setup --set checks=yes` in the developer checkout
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0009-test-fixture-must-not-inherit-developer-setup-answers.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-04T08:19:47Z | chief-1 | - -> todo | created
- 2026-11-05T09:52:51Z | opencode-1 | todo -> in_progress | claimed
- 2026-11-05T09:52:52Z | opencode-1 | in_progress -> todo | claim rolled back | the task branch could not start
- 2026-11-05T16:48:00Z | evren-deep-seek | todo -> in_progress | claimed
- 2026-11-05T16:48:02Z created branch feature/0009-test-fixture-must-not-inherit-developer from develop by evren-deep-seek
- 2026-11-05T17:24:35Z committed: test: test: pin fixture check gate against developer setup answers
