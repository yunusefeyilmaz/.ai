---
id: 0001
title: "Make Gitflow setup choose a valid commit-backed base"
status: in_progress
owner: codex
priority: high
spec: specs/active/0001-gitflow-valid-base.md
created: 2026-10-28T16:22:18Z
updated: 2026-10-28T16:24:55Z
lock: task-0001
branch: fix/0001-gitflow-valid-base
depends_on: null
---

# 0001 - Make Gitflow setup choose a valid commit-backed base

## Intent

Setup can create an unborn default branch such as `master`, then accidentally
use an unresolved branch name as the base for `main`. Make initialization and
all production/integration branch creation use the configured production
name and a valid commit object.

## Acceptance criteria

- [x] Fresh Git initialization points `HEAD` to the configured production
  branch instead of depending on Git's default branch name.
- [x] Existing local branch names are only considered when they resolve to a
  commit; branch creation uses the resolved commit ID.
- [x] Existing configured refs without a commit produce a direct repair
  message instead of being reused as a base.
- [x] `ai check --strict` passes with no errors or warnings.

## Plan

Use `git init --initial-branch=<production>` where available, retain a safe
fallback, and create all missing base branches from commit IDs.

`ai git start` refuses the dirty task/spec ledger created by task setup, so the
task branch was started with the equivalent direct Gitflow branch operation
from `develop` before editing implementation code.

## Notes

## Log

- 2026-10-28T16:22:18Z created
- 2026-10-28T16:22:27Z claimed by codex
- 2026-10-28T16:24:02Z checkpoint by codex (checkpoint, 70%)
- Verification: `ai git setup` succeeded; `ai check --strict` -> 0 errors, 0 warnings.
- Independent review: PASS; invalid unborn-base path reviewed statically, no tests run.
- 2026-10-28T16:24:55Z committed: fix(gitflow): start production on configured branch
