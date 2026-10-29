---
id: 0002
title: "P0 diagnostics: actionable doctor output and safe repair"
status: done
owner: null
priority: high
spec: specs/done/0002-actionable-diagnostics.md
created: 2026-10-29T06:55:07Z
updated: 2026-10-29T07:50:44Z
lock: null
depends_on: 0001
branch: null
merged_into: develop
merged_at: 2026-10-29T07:50:40Z
---

# 0002 - P0 diagnostics: actionable doctor output and safe repair

## Intent

A newcomer who breaks the workspace currently gets a list of warnings with no
next action. Diagnosis is only useful if it names the safe repair.

## Acceptance criteria

- [x] Every `ai doctor` finding with a known safe repair prints the exact next
      command.
- [x] `ai doctor --fix` repairs only idempotent, non-destructive issues: runtime
      directories, missing config, subfolder adapter pointers and ignore rules.
      It reports each change and leaves everything else untouched.
- [x] `ai doctor --fix --json` returns a `fixes` array and the remaining
      findings; the exit code is 0 only when nothing remains.
- [x] Unit tests prove a broken workspace is diagnosed, repaired, and re-checked
      clean without deleting task, spec or Git data.

## Plan

Spec: `specs/active/0002-actionable-diagnostics.md`

1. Give each finding a stable shape: level, message and an optional repair hint.
2. Add `--fix` to the existing doctor path; reuse `ensure_dirs`, config and
   `adopt` rather than new repair logic.
3. Report missing subfolder adapter pointers and ignore rules so the repair is
   observable.
4. Add regression tests, docs and a changelog entry.

## Notes

## Log

- 2026-10-29T06:55:07Z created
- 2026-10-29T07:32:43Z claimed by implementer
- 2026-10-29T07:32:44Z created branch feature/0002-p0-diagnostics-actionable-doctor-output from develop by implementer
- 2026-10-29T07:43:33Z implementation ready: `python -m unittest discover -s tests -q` -> 23 tests OK; `ai check --strict` -> 0 errors, 0 warnings
- 2026-10-29T07:43:51Z committed: feat(doctor): add repair hints and safe fixes
- 2026-10-29T07:43:58Z submitted for independent review by implementer
- 2026-10-29T07:43:59Z released by implementer
- 2026-10-29T07:44:00Z committed: chore: record review-ready state for 0002
- 2026-10-29T07:49:27Z reviewed by reviewer: PASS. Commands: `ai doctor --strict` -> 0 errors, 0 warnings; `ai check --strict` -> 0 errors, 0 warnings (23 tests); `python -m unittest discover -s tests -v` -> 23 tests OK (Python 3.9.10 and 3.10.6); scratch-copy checks for criteria 1-6 plus the safe-repair audit passed.
- 2026-10-29T07:49:54Z committed: docs: record independent review evidence for 0002
- 2026-10-29T07:50:40Z merged feature/0002-p0-diagnostics-actionable-doctor-output into develop by reviewer
- 2026-10-29T07:50:44Z marked done by reviewer
