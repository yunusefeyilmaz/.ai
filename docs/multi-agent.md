# Multi-agent coordination

Several agents may share one checkout. Git protects committed history, not the
working tree: two agents can edit the same file, claim the same task, or create
the same output file at the same time. `.ai` adds a small, explicit coordination
layer on top of the filesystem.

## What is protected

| Resource | Lock name | Acquired by |
|----------|-----------|-------------|
| A task | `task-<id>` | `ai task claim` |
| Task-id allocation | `tasks.index` | `ai task new` (short-lived) |
| A file or subsystem | any name you choose | `ai lock acquire <resource>` |
| The git index | `@git/index` | `ai git begin` (short-lived) |
| The whole project (rare) | `project` | `ai lock acquire project` |

Choose lock names that match the blast radius: `src/billing` is better than
`billing`, and `package.json` is better than `node_modules`.

Resources are repo-relative; absolute paths are rejected. **Overlap counts as
conflict**: `src/billing` conflicts with `src/billing/invoice.py`, and globs such
as `src/*.ts` conflict with matching paths. Acquisition is serialized through a
short-lived `.registry.mutex` directory so the overlap scan cannot race.

## The lock file

A lock is a JSON file at `runtime/locks/<resource>.lock`:

```json
{
  "resource": "task-0001",
  "agent": "implementer",
  "task": "0001",
  "host": "LAPTOP-7",
  "pid": 4812,
  "started_at": "2026-10-27T18:30:00Z",
  "updated_at": "2026-10-27T18:31:10Z",
  "ttl_seconds": 1800
}
```

Creation uses `os.open(path, O_CREAT | O_EXCL | O_WRONLY)`. That single call is
atomic on Windows, Linux and macOS: exactly one process wins, everyone else gets
`FileExistsError`. No read-then-write race.

## Staleness and recovery

A lock is **stale** when any of these is true:

- `updated_at` is older than `locks.staleAfterSeconds` (default 3600).
- The lock file is unreadable or malformed.

The PID and host are recorded for diagnostics, not for staleness. A task claim
outlives the short-lived CLI process that created it, so checking whether the
PID is alive would mark every held task lock stale immediately. Long-running
work must call `ai lock heartbeat` before the TTL expires.

Stale locks may be reclaimed:

```sh
ai lock release task-0001 --force
ai task claim 0001 --agent implementer     # or with --force
ai clean --stale-locks
ai recover --apply                         # structural repairs
```

A **live** lock is a refusal. Do not delete it, do not overwrite its files, and
do not "wait it out" by editing the task. Either work on a different task or
talk to the holder's agent.

## Heartbeats

Long tasks must extend their lock before the TTL expires:

```sh
ai lock heartbeat task-0001 --agent implementer
ai lock heartbeat src/billing --agent implementer
```

A heartbeat rewrites the lock atomically. If the refresh fails because the lock
was stolen, stop editing and re-read the task; you no longer own it.

## Deadlock avoidance

1. **One task per agent session.** Never claim two tasks.
2. **Fixed acquisition order.** When you need more than one lock, acquire them
   in lexical order (`ai/api` before `ai/web`) so two agents cannot form a cycle.
3. **Short lock scope.** Acquire just before editing; release immediately after.
   Do not hold a lock while thinking, reviewing or running unrelated commands.
4. **No task lock while holding a file lock**, unless the file is inside that
   task's own scope. Task locks already serialize the task's owner.
5. **Timeouts are not negotiation.** If a lock is live, the operation failed.
   Report it and move on.
6. **Fixed global order:** task lock, then file locks, then `@git/index`. Release
   in reverse. Never hold `@git/index` while thinking or running tests.

## Task claims are the unit of ownership

The task lock and the task's `owner` field move together:

- `ai task claim` writes the lock, then the task.
- `ai task release` rewrites the task, then removes the lock.
- `ai task done` archives the task, then removes the lock.

If a process dies between these steps, `ai check` reports the inconsistency and
`ai recover --apply` repairs the common cases: owner/lock mismatch, locks on done
tasks, orphan locks, stale locks and orphan handoff markers. The window is small
and visible on purpose.

## Checkpoints in a multi-agent run

A task lock says *who owns the work*; a checkpoint says *where the work is*. Keep
them together:

- Checkpoint at milestones and before a handoff (`ai checkpoint`).
- `ai handoff` refreshes the checkpoint and writes a marker. `ai check` warns if
  the checkpoint is older than the marker.
- A resuming agent runs `ai resume <id>`, reads the drift report, then claims or
  heartbeats the lock before editing.
- Never use a checkpoint to bypass ownership. If another live agent owns the
  task, the checkpoint is read-only information.

## What locks do not do

- They are **advisory**, not enforced by the OS. An agent that ignores the
  protocol can still edit a locked file. The refusal is a social and procedural
  contract backed by `ai check` and CI.
- They are **per checkout**. Two clones of the repository have separate
  `runtime/locks/`. Coordination across clones happens through Git branches and
  pull requests, not through these locks.
- They are **not a substitute for branches**. Parallel work should still use
  separate branches; locks protect the shared working tree, not history.

## A safe concurrent session

```sh
ai status                                  # see tasks and locks
ai task claim 0007 --agent implementer     # atomic; refused if owned
ai lock acquire src/billing --agent implementer --task 0007
# edit only src/billing
ai lock release src/billing --agent implementer
ai check
ai task release 0007 --agent implementer   # or: ai task done 0007 --agent implementer
```
