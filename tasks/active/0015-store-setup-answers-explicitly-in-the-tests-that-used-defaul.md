---
id: 0015
title: "Store setup answers explicitly in the tests that used --defaults"
status: review
owner: null
priority: high
spec: specs/active/0015-store-setup-answers-explicitly-in-the-tests-that-used-defaul.md
depends_on: null
scope_allowed: "lib/tests/test_start.py, lib/tests/test_field_report.py, lib/tests/test_worktree.py, lib/tests/test_chief.py"
scope_forbidden: null
locks: "lib/tests/test_start.py, lib/tests/test_field_report.py, lib/tests/test_worktree.py, lib/tests/test_chief.py"
branch: feature/0015-store-setup-answers-explicitly-in-the-te
created: 2026-11-03T09:02:13Z
updated: 2026-11-03T09:05:27Z
lock: null
submitted_by: buffy-s3
---

# 0015 - Store setup answers explicitly in the tests that used --defaults

## Intent

Making `ai setup --defaults` a real human gate means the test suite can no longer use it as a non-interactive shortcut; those tests must state the answers they rely on.

## Acceptance criteria

- [ ] no test calls `ai setup --defaults` outside the gate's own tests
- [ ] the modules that previously relied on it are green
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0015-store-setup-answers-explicitly-in-the-tests-that-used-defaul.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T09:02:13Z | orchestrator | - -> todo | created
- 2026-11-03T09:02:14Z | buffy-s3 | todo -> in_progress | claimed
- 2026-11-03T09:02:15Z created branch feature/0015-store-setup-answers-explicitly-in-the-te from develop by buffy-s3
- 2026-11-03T09:05:25Z committed: fix: state the setup answers the tests rely on and keep worktrees ignored
- 2026-11-03T09:05:27Z | buffy-s3 | in_progress -> review | submitted for independent review | check passed @ff8df36e by buffy-s3 (no commands)
