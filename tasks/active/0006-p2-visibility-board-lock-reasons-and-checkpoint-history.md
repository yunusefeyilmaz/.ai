---
id: 0006
title: "P2 visibility: board, lock reasons and checkpoint history"
status: in_progress
owner: buffy
priority: low
spec: specs/active/0006-p2-visibility-board-lock-reasons-and-checkpoint-history.md
created: 2026-10-29T06:55:09Z
updated: 2026-10-29T14:13:48Z
lock: task-0006
depends_on: 0004
branch: feature/0006-p2-visibility-board-lock-reasons-and-che
---

# 0006 - P2 visibility: board, lock reasons and checkpoint history

## Intent

The task board shows only titles. When a session waits, the human has to read
lock files and logs to learn why. Show the reason in one view.

## Acceptance criteria

- [x] `ai status --board` renders active tasks as a dependency-aware list with
      owner, status and checkpoint age.
- [x] Each held lease shows owner, task, TTL and remaining time; each refusal is
      explained by the conflicting resource.
- [x] The view is read-only, works without colour and degrades to plain text.
- [x] Snapshot tests cover empty, single-task and blocked-work states.

## Plan

1. Build the view from `load_tasks`, `list_locks` and checkpoint mtimes.
2. Keep `ai status` output stable for scripts; add the board as an option.
3. Record the conflicting resource on `lock_refused` events so refusals can be
   explained.

## Notes

- Spec: `specs/active/0006-p2-visibility-board-lock-reasons-and-checkpoint-history.md`
  (approved by user on 2026-10-29).
- `render_board` in `scripts/ai.py` owns the text; `board_task_rows` does the
  dependency ordering (dependencies first, then priority and id) and computes
  the waiting reason. The view reads with `list_locks(ensure=False)` and
  `read_events()` so it creates no state.
- `--board` is short-circuited before `list_handoff_markers()`, which calls
  `ensure_dirs()`; that is why plain `ai status` is untouched.
- `ai lock acquire` and a refused task claim now record `conflict: <resource>`
  on `lock_refused` events; events without the field render as
  `conflict unknown`.
- Tests: `tests/test_board.py` (9 tests: three snapshots, lease/refusal rows,
  plain-text, read-only and unchanged plain/JSON status).

## Log

- 2026-10-29T06:55:09Z created
- 2026-10-29T09:08:15Z claimed by cline
- 2026-10-29T14:10:00Z claim cleared by `ai recover --apply` after the cline lease expired; task returned to todo
- 2026-10-29T14:20:00Z spec written at `specs/active/0006-p2-visibility-board-lock-reasons-and-checkpoint-history.md` and linked
- 2026-10-29T14:22:00Z claimed by buffy
- 2026-10-29T14:23:00Z created branch feature/0006-p2-visibility-board-lock-reasons-and-che from develop by buffy
- 2026-10-29T14:35:00Z implemented `ai status --board`, `conflict` on lock_refused events, GUIDE entry and `tests/test_board.py`
- 2026-10-29T14:06:42Z claimed by buffy
- 2026-10-29T14:06:52Z created branch feature/0006-p2-visibility-board-lock-reasons-and-che from develop by buffy
- 2026-10-29T14:13:38Z checkpoint by buffy (checkpoint, 60%)
- 2026-10-29T14:13:48Z committed: feat(status): add a read-only board view with lease and refusal reasons
