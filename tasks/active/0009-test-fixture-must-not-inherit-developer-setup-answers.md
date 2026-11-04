---
id: 0009
title: "Test fixture must not inherit developer setup answers"
status: todo
owner: null
priority: high
spec: specs/active/0009-test-fixture-must-not-inherit-developer-setup-answers.md
depends_on: null
scope_allowed: "lib/tests/**"
scope_forbidden: null
locks: "lib/tests/**"
branch: feature/0009-test-fixture-must-not-inherit-developer
created: 2026-11-04T08:19:47Z
updated: 2026-11-04T09:22:56Z
lock: null
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
- 2026-11-04T08:20:05Z | impl-1 | todo -> in_progress | claimed
- 2026-11-04T08:20:06Z | impl-1 | in_progress -> todo | claim rolled back | the task branch could not start
- 2026-11-04T08:20:41Z | impl-1 | todo -> in_progress | claimed
- 2026-11-04T08:20:43Z created branch feature/0009-test-fixture-must-not-inherit-developer from develop by impl-1
- 2026-11-04T09:13:51Z checkpoint by impl-1 (checkpoint, ?%)
- 2026-11-04T09:14:23Z committed: test: test: isolate fixtures from developer setup answers
- 2026-11-04T09:22:56Z | impl-1 | in_progress -> todo | released
