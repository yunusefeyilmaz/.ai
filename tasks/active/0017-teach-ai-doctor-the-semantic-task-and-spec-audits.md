---
id: 0017
title: "Teach ai doctor the semantic task and spec audits"
status: review
owner: buffy-reviewer
priority: high
spec: specs/active/0017-teach-ai-doctor-the-semantic-task-and-spec-audits.md
depends_on: null
scope_allowed: "lib/runtime/health.py, lib/tests/test_doctor_semantics.py"
scope_forbidden: null
locks: "lib/runtime/health.py, lib/tests/test_doctor_semantics.py"
branch: feature/0017-teach-ai-doctor-the-semantic-task-and-sp
created: 2026-11-03T09:12:54Z
updated: 2026-11-03T09:46:07Z
lock: task-0017
submitted_by: buffy-s4
---

# 0017 - Teach ai doctor the semantic task and spec audits

## Intent

ai doctor checked the environment but not the meaning of the ledger: an active task can have an unfilled spec, a dependency cycle, in_progress without an owner, or no branch, and nothing reports it.

## Acceptance criteria

- [ ] ai doctor warns about every active task whose spec is missing, unreadable or still the template, with the spec path and a fill-it hint
- [ ] ai doctor reports dependency cycles among active tasks as an error naming the cycle, and still reports unknown dependencies as before
- [ ] ai doctor warns about in_progress/review/blocked tasks with no owner, and about in_progress/review tasks with no branch while git is enabled, each with the next command as the hint
- [ ] a clean workspace with no active tasks still reports zero findings and ai doctor --strict exits 0
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0017-teach-ai-doctor-the-semantic-task-and-spec-audits.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T09:12:54Z | orchestrator | - -> todo | created
- 2026-11-03T09:28:51Z | buffy-s4 | todo -> in_progress | claimed
- 2026-11-03T09:28:52Z created branch feature/0017-teach-ai-doctor-the-semantic-task-and-sp from develop by buffy-s4
- 2026-11-03T09:45:56Z committed: feat: audit specs, dependency cycles, owners and branches in ai doctor
- 2026-11-03T09:46:02Z | buffy-s4 | in_progress -> review | submitted for independent review | check passed @e41f8301 by buffy-s4 (no commands)
- 2026-11-03T09:46:06Z | buffy-reviewer | review -> review | claimed
- 2026-11-03T09:46:07Z committed: chore: chore(0017): record the review handover
