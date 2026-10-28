---
id: 0001
title: "Treat unborn HEAD as no commit during Gitflow setup"
status: review
owner: null
priority: high
spec: specs/active/0001-unborn-head-detection.md
created: 2026-10-28T16:34:03Z
updated: 2026-10-28T16:36:15Z
lock: null
branch: fix/0001-unborn-head-detection
depends_on: null
---

# 0001 - Treat unborn HEAD as no commit during Gitflow setup

## Intent

In an unborn repository, `git rev-parse HEAD` can emit the text `HEAD` while
returning a failure code. `git_state()` currently trusts that output and Gitflow
tries to create the production branch from a nonexistent commit.

## Acceptance criteria

- [x] `git_state()` accepts `HEAD` only when Git successfully resolves it to a
  commit object ID.
- [x] `ai check --strict` passes with no errors or warnings.

## Plan

Check the `rev-parse` exit status and require a resolved commit hash before
setting `state.head`.

`ai git start` refuses the dirty task/spec ledger, so this task branch was
started directly from `develop` before editing implementation code.

## Notes

## Log

- 2026-10-28T16:34:03Z created
- 2026-10-28T16:34:11Z claimed by codex
- 2026-10-28T16:34:43Z checkpoint by codex (checkpoint, 70%)
- Verification: `ai git setup` succeeded in committed repository; `ai check --strict` -> 0 errors, 0 warnings.
- Independent review: PASS; unborn `HEAD` no longer resolves to a base. No isolated unborn-repository test was run.
- 2026-10-28T16:36:07Z committed: fix(git-state): ignore unresolved unborn HEAD
- 2026-10-28T16:36:11Z submitted for independent review by codex
- 2026-10-28T16:36:11Z released by codex
- 2026-10-28T16:36:15Z committed: chore(task): record review release state
