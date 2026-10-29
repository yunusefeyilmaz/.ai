---
id: 0007
title: "P0 first-run: keep the start path branchable"
status: done
owner: null
priority: high
spec: specs/done/0007-p0-first-run-keep-the-start-path-branchable.md
created: 2026-10-29T07:17:08Z
updated: 2026-10-29T07:28:01Z
lock: null
depends_on: 0001
branch: null
merged_into: develop
merged_at: 2026-10-29T07:27:55Z
---

# 0007 - P0 first-run: keep the start path branchable

## Intent

The first independent review found that the printed first-run loop still fails:
`ai start --agent` leaves the new task and spec uncommitted, so the next
`ai git start` refuses to run. A ledger with only archived tasks makes `start`
try to claim a done task. Both break the one-command promise on the very first
use. The Git status parser also drops the first character of the first porcelain
entry, which can hide a staged path from `ai git verify`.

## Acceptance criteria

- [x] After `ai start --agent <name>`, `ai git start` for that task succeeds even
      though the task and spec are still uncommitted.
- [x] `ai git start` still refuses when a product file is modified or untracked.
- [x] With only done tasks, `ai start --agent <name>` creates the next task,
      claims it, and never targets the archived one.
- [x] With an active task present, `ai start` creates nothing.
- [x] `ai git verify --strict` sees the first staged path in full and reports it
      covered by a lease.
- [x] The suite covers the four scenarios and `ai check --strict` is green.

## Plan

Spec: `specs/active/0007-p0-first-run-keep-the-start-path-branchable.md`

1. Treat `tasks/` and `specs/` as ledger paths that do not block a task branch;
   product paths still do.
2. Select only active tasks in `start` and create a starter when none exist.
3. Parse `git status --porcelain` without trimming its first column.
4. Add regression tests and changelog entries.

## Notes

## Log

- 2026-10-29T07:17:08Z created
- 2026-10-29T07:17:08Z claimed by implementer
- 2026-10-29T07:17:25Z created branch feature/0007-p0-first-run-keep-the-start-path-brancha from develop by implementer
- 2026-10-29T07:20:53Z committed: fix(onboarding): keep the first-run loop branchable
- 2026-10-29T07:20:57Z submitted for independent review by implementer
- 2026-10-29T07:20:58Z released by implementer
- 2026-10-29T07:20:59Z committed: chore: record review-ready state for 0007
- 2026-10-29T07:26:57Z reviewed by reviewer: PASS. `ai doctor --strict` -> 0 errors, 0 warnings; `ai check --strict` -> 0 errors, 0 warnings; `python -m unittest discover -s tests -v` -> 17 tests OK; scratch-copy checks passed for `ai start` + uncommitted ledger branch, product-change refusal, done-only ledger, active-task reuse, and first porcelain entry; `ai git commit`/`ai git finish`/`ai recover` and the lite checkpoint rule showed no regression.
- 2026-10-29T07:27:18Z committed: docs: record independent review evidence for 0007
- 2026-10-29T07:27:55Z merged feature/0007-p0-first-run-keep-the-start-path-brancha into develop by reviewer
- 2026-10-29T07:28:01Z marked done by reviewer
