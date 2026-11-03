---
id: 0004
title: "Make review a real git gate (branch, clean tree, HEAD) and fix rename parsing"
status: todo
owner: null
priority: high
spec: specs/active/0004-make-review-a-real-git-gate-branch-clean-tree-head-and-fix-r.md
depends_on: 0003
scope_allowed: "lib/git/repo.py, lib/tasks/gates.py, lib/cmd/task.py, lib/tests/test_review_gate.py"
scope_forbidden: null
locks: "lib/git/repo.py, lib/tasks/gates.py, lib/cmd/task.py, lib/tests/test_review_gate.py"
created: 2026-11-03T07:17:31Z
updated: 2026-11-03T07:17:31Z
lock: null
---

# 0004 - Make review a real git gate (branch, clean tree, HEAD) and fix rename parsing

## Intent

Review passes without checking the task branch or a clean product tree, then git finish fails after handover; git_state also mis-parses porcelain rename records, which would make such a gate unreliable.

## Acceptance criteria

- [ ] `python lib/tests/run.py test_review_gate` is green
- [ ] porcelain -z rename/copy records consume both paths and never create a phantom dirty entry
- [ ] review refuses when the current branch differs from the task branch, naming the mismatch and the next command
- [ ] review refuses when product files are uncommitted, listing them
- [ ] review refuses when recorded evidence belongs to another HEAD (when evidence exists)
- [ ] review still passes for a clean task branch, and for a workspace without Git
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0004-make-review-a-real-git-gate-branch-clean-tree-head-and-fix-r.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T07:17:31Z | orchestrator | - -> todo | created
