---
id: 0003
title: "Fix Gitflow bootstrap for root and unborn repositories"
status: review
owner: null
priority: high
spec: specs/active/0003-gitflow-bootstrap.md
created: 2026-10-28T16:08:49Z
updated: 2026-10-28T16:16:05Z
lock: null
branch: null
depends_on: null
merged_into: develop
merged_at: 2026-10-28T16:16:05Z
---

# 0003 - Fix Gitflow bootstrap for root and unborn repositories

## Intent

Gitflow setup fails for standalone `.ai` checkouts and can treat an unborn
branch as a usable base. Fix bootstrap so agents can start task branches in
both the reusable framework repository and adopted host projects.

## Acceptance criteria

- [x] Setup resolves a standalone `.ai` Git checkout to itself while adopted
  subfolder installs target their host project.
- [x] Setup filters local branches to commit-backed refs before selecting a
  production base and falls back to the explicit baseline confirmation flow.
- [x] Re-running setup does not rewrite an already-correct local commit template.
- [x] `ai check --strict` passes with no errors or warnings.

## Plan

Implement root resolution and commit-backed base detection in `scripts/ai.py`,
document the behavior, then run the workspace checks and request an independent
review.

## Notes

Gitflow setup initially targeted the parent because this checkout itself is
named `.ai`. Created `main` and `develop` from the existing `master` history,
then started this task branch directly because the CLI setup defect prevented
`ai git start` before the fix.

## Log

- 2026-10-28T16:08:49Z created
- 2026-10-28T16:09:01Z claimed by codex
- 2026-10-28T16:12:57Z checkpoint by codex (checkpoint, 70%)
- Verification: `ai git setup` succeeded; `ai check --strict` -> 0 errors, 0 warnings.
- Independent review: PASS; unborn-branch flow reviewed statically, not exercised.
- 2026-10-28T16:14:29Z committed: fix(gitflow): handle unborn Gitflow bootstrap
- 2026-10-28T16:15:37Z submitted for independent review by codex
- 2026-10-28T16:15:37Z released by codex
- 2026-10-28T16:15:48Z committed: chore(task): record review release state
- 2026-10-28T16:16:05Z merged fix/0003-gitflow-bootstrap into develop by reviewer
