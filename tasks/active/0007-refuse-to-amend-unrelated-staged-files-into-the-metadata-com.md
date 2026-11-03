---
id: 0007
title: "Refuse to amend unrelated staged files into the metadata commit"
status: review
owner: reviewer-1
priority: high
spec: specs/active/0007-refuse-to-amend-unrelated-staged-files-into-the-metadata-com.md
depends_on: null
scope_allowed: "lib/git/repo.py, lib/tests/test_metadata_commit.py"
scope_forbidden: null
locks: "lib/git/repo.py, lib/tests/test_metadata_commit.py"
branch: null
created: 2026-11-03T07:45:14Z
updated: 2026-11-03T08:06:31Z
lock: task-0007
submitted_by: cline-impl
merged_into: develop
merged_at: 2026-11-03T08:06:31Z
---

# 0007 - Refuse to amend unrelated staged files into the metadata commit

## Intent

`commit_task_metadata` runs `git commit --amend` whenever anything is staged, so files the user staged earlier silently join the previous commit.

## Acceptance criteria

- [ ] `python lib/tests/run.py test_metadata_commit` is green
- [ ] the amend runs only when the staged paths are exactly the task file and the board
- [ ] an unrelated staged path makes the amend skip with a warning that names the path, and leaves it staged
- [ ] the non-amend path still creates a commit with the given message
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0007-refuse-to-amend-unrelated-staged-files-into-the-metadata-com.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T07:45:14Z | orchestrator | - -> todo | created
- 2026-11-03T07:54:21Z | cline-impl | todo -> in_progress | claimed
- 2026-11-03T07:54:22Z created branch feature/0007-refuse-to-amend-unrelated-staged-files-i from develop by cline-impl
- 2026-11-03T07:58:58Z committed: fix: stop folding unrelated staged files into the metadata amend
- 2026-11-03T07:59:10Z | cline-impl | in_progress -> review | submitted for independent review | check passed @7a12b785 by cline-impl (no commands)
- 2026-11-03T08:01:58Z | reviewer-1 | review -> review | claimed
- 2026-11-03T08:03:44Z committed: chore: record the review claim for task 0007
- 2026-11-03T08:06:18Z committed: chore: refresh the board timestamp
- 2026-11-03T08:06:31Z merged feature/0007-refuse-to-amend-unrelated-staged-files-i into develop by reviewer-1
