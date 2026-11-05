---
id: 0004
title: "No silent green: fail loudly when the project has no checks"
status: todo
owner: null
priority: medium
spec: specs/active/0004-no-silent-green-fail-loudly-when-the-project-has-no-checks.md
depends_on: null
scope_allowed: "lib/cmd/check.py, lib/config/settings.py, lib/tests/test_check_gate.py"
scope_forbidden: null
locks: "lib/cmd/check.py, lib/config/settings.py, lib/tests/test_check_gate.py"
created: 2026-11-04T08:14:04Z
updated: 2026-11-05T09:52:53Z
lock: null
---

# 0004 - No silent green: fail loudly when the project has no checks

## Intent

`ai check` looks successful when the project has no checks configured, and a review can pass on that empty evidence. An empty gate must be visible, not silent.

## Acceptance criteria

- [ ] `ai check` exits non-zero with an actionable message when no project checks are configured
- [ ] An explicit opt-out (or documented flag) exists for projects that intentionally run no checks, and it is printed in the output
- [ ] `ai task review` cannot pass on an empty check result in strict mode
- [ ] Regression tests cover both the refusal and the opt-out
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0004-no-silent-green-fail-loudly-when-the-project-has-no-checks.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-04T08:14:04Z | chief-1 | - -> todo | created
- 2026-11-05T09:52:52Z | opencode-1 | todo -> in_progress | claimed
- 2026-11-05T09:52:53Z | opencode-1 | in_progress -> todo | claim rolled back | the task branch could not start
