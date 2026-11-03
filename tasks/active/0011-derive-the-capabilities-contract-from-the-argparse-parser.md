---
id: 0011
title: "Derive the capabilities contract from the argparse parser"
status: review
owner: null
priority: medium
spec: specs/active/0011-derive-the-capabilities-contract-from-the-argparse-parser.md
depends_on: null
scope_allowed: "lib/cmd/capabilities.py, lib/tests/test_capabilities.py"
scope_forbidden: null
locks: "lib/cmd/capabilities.py, lib/tests/test_capabilities.py"
branch: null
created: 2026-11-03T08:44:09Z
updated: 2026-11-03T08:55:07Z
lock: null
submitted_by: buffy-s3
merged_into: develop
merged_at: 2026-11-03T08:55:07Z
---

# 0011 - Derive the capabilities contract from the argparse parser

## Intent

`ai capabilities` is hand-maintained, so it silently misses real flags (`ai check --task/--agent/--no-commands`) and machine-readable clients get a contract that disagrees with the parser.

## Acceptance criteria

- [ ] every command the parser defines appears in `ai capabilities` output
- [ ] every option string each command defines appears in the published flags for that command
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0011-derive-the-capabilities-contract-from-the-argparse-parser.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T08:44:09Z | orchestrator | - -> todo | created
- 2026-11-03T08:44:44Z | buffy-s3 | todo -> in_progress | claimed
- 2026-11-03T08:44:45Z created branch feature/0011-derive-the-capabilities-contract-from-th from develop by buffy-s3
- 2026-11-03T08:46:24Z committed: feat: derive the capabilities contract from the argparse parser
- 2026-11-03T08:55:04Z | buffy-s3 | in_progress -> review | submitted for independent review | check passed @6bc2797f by buffy-s3 (no commands)
- 2026-11-03T08:55:07Z merged feature/0011-derive-the-capabilities-contract-from-th into develop by buffy-reviewer
