---
id: 0007
title: "Refuse to amend unrelated staged files into the metadata commit"
status: todo
owner: null
priority: high
spec: specs/active/0007-refuse-to-amend-unrelated-staged-files-into-the-metadata-com.md
depends_on: null
scope_allowed: "lib/git/repo.py, lib/tests/test_metadata_commit.py"
scope_forbidden: null
locks: "lib/git/repo.py, lib/tests/test_metadata_commit.py"
created: 2026-11-03T07:45:14Z
updated: 2026-11-03T07:45:14Z
lock: null
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
