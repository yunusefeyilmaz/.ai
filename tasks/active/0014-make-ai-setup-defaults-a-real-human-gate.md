---
id: 0014
title: "Make ai setup --defaults a real human gate"
status: todo
owner: null
priority: high
spec: specs/active/0014-make-ai-setup-defaults-a-real-human-gate.md
depends_on: null
scope_allowed: "lib/cmd/setup.py, lib/tests/test_setup_gate.py"
scope_forbidden: null
locks: "lib/cmd/setup.py, lib/tests/test_setup_gate.py"
created: 2026-11-03T08:44:09Z
updated: 2026-11-03T08:44:09Z
lock: null
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
