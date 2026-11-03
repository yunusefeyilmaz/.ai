---
id: 0014
title: "Make ai setup --defaults a real human gate"
status: review
owner: null
priority: high
spec: specs/active/0014-make-ai-setup-defaults-a-real-human-gate.md
depends_on: null
scope_allowed: "lib/cmd/setup.py, lib/tests/test_setup_gate.py, lib/tests/test_chief.py"
scope_forbidden: null
locks: "lib/cmd/setup.py, lib/tests/test_setup_gate.py, lib/tests/test_chief.py"
branch: null
created: 2026-11-03T08:44:09Z
updated: 2026-11-03T08:59:31Z
lock: null
submitted_by: buffy-s3
merged_into: develop
merged_at: 2026-11-03T08:59:31Z
---

# 0014 - Make ai setup --defaults a real human gate

## Intent

`ai setup --defaults` accepts the recommended answers in one non-interactive command, so an agent can fake the chief's required human approval.

## Acceptance criteria

- [ ] `ai setup --defaults` without `--yes` is refused
- [ ] `ai setup --defaults` requires an interactive terminal
- [ ] task creation is still refused while preferences are unconfirmed
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0014-make-ai-setup-defaults-a-real-human-gate.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T08:44:09Z | orchestrator | - -> todo | created
- 2026-11-03T08:58:37Z | buffy-s3 | todo -> in_progress | claimed
- 2026-11-03T08:58:38Z created branch feature/0014-make-ai-setup-defaults-a-real-human-gate from develop by buffy-s3
- 2026-11-03T08:59:28Z committed: fix: require explicit human confirmation for ai setup --defaults
- 2026-11-03T08:59:29Z | buffy-s3 | in_progress -> review | submitted for independent review | check passed @1166d71f by buffy-s3 (no commands)
- 2026-11-03T08:59:31Z merged feature/0014-make-ai-setup-defaults-a-real-human-gate into develop by buffy-reviewer
