---
id: 0006
title: "P2 visibility: board, lock reasons and checkpoint history"
status: in_progress
owner: cline
priority: low
spec: null
created: 2026-10-29T06:55:09Z
updated: 2026-10-29T09:08:15Z
lock: task-0006
depends_on: 0004
---

# 0006 - P2 visibility: board, lock reasons and checkpoint history

## Intent

The task board shows only titles. When a session waits, the human has to read
lock files and logs to learn why. Show the reason in one view.

## Acceptance criteria

- [ ] `ai status --board` renders active tasks as a dependency-aware list with
      owner, status and checkpoint age.
- [ ] Each held lease shows owner, task, TTL and remaining time; each refusal is
      explained by the conflicting resource.
- [ ] The view is read-only, works without colour and degrades to plain text.
- [ ] Snapshot tests cover empty, single-task and blocked-work states.

## Plan

1. Build the view from `load_tasks`, `list_locks` and checkpoint mtimes.
2. Keep `ai status` output stable for scripts; add the board as an option.

## Notes

## Log

- 2026-10-29T06:55:09Z created
- 2026-10-29T09:08:15Z claimed by cline
