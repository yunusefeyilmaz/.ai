---
id: 0005
title: "Require the reviewer to claim a task before requesting changes"
status: review
owner: reviewer
priority: high
spec: specs/active/0005-require-the-reviewer-to-claim-a-task-before-requesting-chang.md
depends_on: 0004
scope_allowed: "lib/tasks/gates.py, lib/cmd/task.py, lib/tests/test_request_changes.py, lib/tests/test_protocol.py, lib/tests/test_field_report.py, lib/tests/test_chief.py, AGENTS.md, docs/task-flow.md"
scope_forbidden: null
locks: "lib/tasks/gates.py, lib/cmd/task.py, lib/tests/test_request_changes.py, lib/tests/test_protocol.py, lib/tests/test_field_report.py, lib/tests/test_chief.py, AGENTS.md, docs/task-flow.md"
branch: feature/0005-require-the-reviewer-to-claim-a-task-bef
created: 2026-11-03T07:17:31Z
updated: 2026-11-03T07:40:45Z
lock: task-0005
submitted_by: implementer
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
- 2026-11-03T07:36:08Z | implementer | todo -> in_progress | claimed
- 2026-11-03T07:36:10Z created branch feature/0005-require-the-reviewer-to-claim-a-task-bef from develop by implementer
- 2026-11-03T07:38:01Z checkpoint by implementer (checkpoint, ?%)
- 2026-11-03T07:40:37Z committed: fix: require the reviewer to hold the claim before requesting changes
- 2026-11-03T07:40:41Z | implementer | in_progress -> review | submitted for independent review | check passed @22ae83e8 by implementer (no commands)
- 2026-11-03T07:40:45Z | reviewer | review -> review | claimed
