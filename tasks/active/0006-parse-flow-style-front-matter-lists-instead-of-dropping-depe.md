---
id: 0006
title: "Parse flow-style front matter lists instead of dropping dependencies"
status: review
owner: reviewer
priority: high
spec: specs/active/0006-parse-flow-style-front-matter-lists-instead-of-dropping-depe.md
depends_on: null
scope_allowed: "lib/tasks/store.py, lib/tests/test_frontmatter_lists.py"
scope_forbidden: null
locks: "lib/tasks/store.py, lib/tests/test_frontmatter_lists.py"
branch: null
created: 2026-11-03T07:45:14Z
updated: 2026-11-03T07:48:21Z
lock: task-0006
submitted_by: implementer
merged_into: develop
merged_at: 2026-11-03T07:48:21Z
---

# 0006 - Parse flow-style front matter lists instead of dropping dependencies

## Intent

Models routinely emit depends_on: [0001, 0002]; the hand-written parser keeps that as one opaque string, so dependencies and scope silently vanish.

## Acceptance criteria

- [ ] `python lib/tests/run.py test_frontmatter_lists` is green
- [ ] `depends_on: [0001, 0002]` parses to two dependency ids and `board_dependencies` returns both
- [ ] quoted items, spacing and an empty `[]` are handled without leaving brackets in the value
- [ ] an unterminated flow list is reported as a front-matter problem instead of being silently accepted
- [ ] block and quoted scalar front matter keeps its current behavior
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0006-parse-flow-style-front-matter-lists-instead-of-dropping-depe.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T07:45:14Z | orchestrator | - -> todo | created
- 2026-11-03T07:45:39Z | implementer | todo -> in_progress | claimed
- 2026-11-03T07:45:41Z created branch feature/0006-parse-flow-style-front-matter-lists-inst from develop by implementer
- 2026-11-03T07:47:42Z checkpoint by implementer (flow-list parser and tests are green, 80%)
- 2026-11-03T07:47:46Z committed: fix: fix: parse flow-style front matter lists instead of dropping them
- 2026-11-03T07:47:58Z | implementer | in_progress -> review | submitted for independent review | check passed @b1e57411 by implementer (no commands)
- 2026-11-03T07:48:09Z | reviewer | review -> review | claimed
- 2026-11-03T07:48:21Z merged feature/0006-parse-flow-style-front-matter-lists-inst into develop by reviewer
