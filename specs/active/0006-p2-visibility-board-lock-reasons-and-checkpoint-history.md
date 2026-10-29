---
status: approved
task: 0006
approved_by: user
approved_on: 2026-10-29
---

# P2 visibility: board, lock reasons and checkpoint history

## Intent

The task board shows only titles. When a session waits, the human has to read lock files and logs to learn why. Show the reason in one view.

## Behavior

### Board View

#### Changed

- `ai status --board` renders active tasks as a dependency-aware list showing:
  - Task id, title, owner, status, priority
  - Depends-on relationships (which tasks are blocked by what)
  - Checkpoint age (time since last checkpoint for in_progress tasks)
  - Whether the task is blocked and by what

#### Preserved

- Existing `ai status` output (without `--board`) remains unchanged
- `ai status --json` continues to work for scriptable output

### Lock Reason Visibility

#### Changed

- Each held lease shows: owner, task, TTL, remaining time
- Each lock refusal is explained by the conflicting resource and the holder
- `ai lock status --json` includes refusal reasons and conflicting lock details

#### Preserved

- Existing lock acquire/release/heartbeat behavior unchanged
- Locks remain advisory with TTL

### Read-Only View

#### Changed

- The board view is read-only; it never modifies task or lock state
- Works without colour; degrades to plain text on non-TTY output

#### Preserved

- No new state is written by the board view

## Acceptance criteria

- [x] `ai status --board` renders active tasks as a dependency-aware list with owner, status and checkpoint age
- [x] Each held lease shows owner, task, TTL and remaining time; each refusal is explained by the conflicting resource
- [x] The view is read-only, works without colour and degrades to plain text
- [x] Snapshot tests cover empty, single-task and blocked-work states
- [x] `ai check --strict` passes

## Out of scope

- Modifying task/lock state from the board view
- Adding notification or alerting based on board state
- Changing lock TTL or heartbeat mechanics

## Status

Approved by user on 2026-10-29. Implemented and verified with `ai check --strict` on 2026-10-29.