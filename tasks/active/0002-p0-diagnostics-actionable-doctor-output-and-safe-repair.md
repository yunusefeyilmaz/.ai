---
id: 0002
title: "P0 diagnostics: actionable doctor output and safe repair"
status: todo
owner: null
priority: high
spec: null
created: 2026-10-29T06:55:07Z
updated: 2026-10-29T06:55:07Z
lock: null
depends_on: 0001
---

# 0002 - P0 diagnostics: actionable doctor output and safe repair

## Intent

A newcomer who breaks the workspace currently gets a list of warnings with no
next action. Diagnosis is only useful if it names the safe repair.

## Acceptance criteria

- [ ] Every `ai doctor` finding with a known safe repair prints the exact next
      command.
- [ ] `ai doctor --fix` repairs only idempotent, non-destructive issues: runtime
      directories, missing config, subfolder adapter pointers and ignore rules.
      It reports each change and leaves everything else untouched.
- [ ] `ai doctor --fix --json` returns a `fixes` array and the remaining
      findings; the exit code is 0 only when nothing remains.
- [ ] Unit tests prove a broken workspace is diagnosed, repaired, and re-checked
      clean without deleting task, spec or Git data.

## Plan

1. Give each finding a stable code and a repair hint.
2. Add `--fix` to the existing doctor path; reuse `ensure_dirs`, config and
   `adopt` rather than new repair logic.

## Notes

## Log

- 2026-10-29T06:55:07Z created
