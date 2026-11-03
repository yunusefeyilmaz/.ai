---
id: 0005
title: "Require the reviewer to claim a task before requesting changes"
status: todo
owner: null
priority: high
spec: specs/active/0005-require-the-reviewer-to-claim-a-task-before-requesting-chang.md
depends_on: 0004
scope_allowed: "lib/tasks/gates.py, lib/cmd/task.py, lib/tests/test_request_changes.py, lib/tests/test_protocol.py, lib/tests/test_field_report.py, lib/tests/test_chief.py"
scope_forbidden: null
locks: "lib/tasks/gates.py, lib/cmd/task.py, lib/tests/test_request_changes.py, lib/tests/test_protocol.py, lib/tests/test_field_report.py, lib/tests/test_chief.py"
created: 2026-11-03T07:17:31Z
updated: 2026-11-03T07:17:31Z
lock: null
---

# 0005 - Require the reviewer to claim a task before requesting changes

## Intent

Any agent can currently send any task in review back, which breaks the one-task-one-owner invariant and lets an observer disrupt delivery.

## Acceptance criteria

- [ ] `python lib/tests/run.py test_request_changes` is green
- [ ] request-changes by an agent without the live review claim is refused with the claiming command in the message
- [ ] a reviewer that claimed the task with `ai task next --review` can still request changes
- [ ] the submitter and non-review states keep their existing refusals
- [ ] existing suite expectations are updated only where the new claim requirement applies
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0005-require-the-reviewer-to-claim-a-task-before-requesting-chang.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T07:17:31Z | orchestrator | - -> todo | created
