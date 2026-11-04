---
id: 0010
title: "'Green baseline: ruff and mypy must pass on develop'"
status: done
owner: implementer
priority: high
spec: specs/done/0010-green-baseline-ruff-and-mypy-must-pass-on-develop.md
depends_on: null
scope_allowed: "'lib/ui/**, pyproject.toml'"
scope_forbidden: null
locks: "'lib/ui/**, pyproject.toml'"
branch: null
created: 2026-11-04T09:22:56Z
updated: 2026-11-04T15:21:18Z
lock: null
changes_requested_by: reviewer
reviewed_by: reviewer
reviewed_at: 2026-11-04T15:10:06Z
merged_into: develop
merged_at: 2026-11-04T15:21:18Z
---

# 0010 - Green baseline: ruff and mypy must pass on develop

## Intent

<!-- What problem does this solve? Who is it for? -->

## Acceptance criteria

- [x]

## Plan

Spec: `specs/active/0010-green-baseline-ruff-and-mypy-must-pass-on-develop.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-04T09:22:56Z | chief-1 | - -> todo | created
- 2026-11-04T09:23:10Z | impl-1 | todo -> in_progress | claimed
- 2026-11-04T09:23:12Z | impl-1 | in_progress -> todo | claim rolled back | the task branch could not start
- 2026-11-04T13:45:55Z | impl-1 | todo -> in_progress | claimed
- 2026-11-04T13:45:57Z | impl-1 | in_progress -> todo | claim rolled back | the task branch could not start
- 2026-11-04T14:34:37Z | impl-1 | todo -> in_progress | claimed
- 2026-11-04T14:34:39Z created branch feature/0010-green-baseline-ruff-and-mypy-must-pass-o from develop by impl-1
- 2026-11-04T14:34:46Z checkpoint by impl-1 (checkpoint, ?%)
- 2026-11-04T14:35:07Z checkpoint by impl-1 (checkpoint, ?%)
- 2026-11-04T14:58:40Z | impl-1 | review -> review | released
- 2026-11-04T14:58:43Z | reviewer | review -> review | claimed
- 2026-11-04T14:58:44Z | reviewer | review -> changes_requested | mypy --platform linux has 3 false positive errors in Windows-guarded code (term.py:211-214); ruff passes, default mypy passes
- 2026-11-04T15:03:02Z | implementer | changes_requested -> in_progress | claimed
- 2026-11-04T15:03:04Z switched to branch feature/0010-green-baseline-ruff-and-mypy-must-pass-o from develop by implementer
- 2026-11-04T15:10:06Z | reviewer | review -> done | approved | evidence invalidated: changes requested by reviewer
- 2026-11-04T15:21:18Z merged feature/0010-green-baseline-ruff-and-mypy-must-pass-o into develop by impl-1
