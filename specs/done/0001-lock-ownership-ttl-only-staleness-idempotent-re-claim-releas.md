---
status: draft
task: 0001
approved_by: null
approved_on: null
---

# Lock ownership: TTL-only staleness, idempotent re-claim, release guard

## Intent

A live claim becomes stale after 30s because PID liveness is consulted for task locks, so another agent can steal the task and `ai recover` can reset its owner. Re-claiming your own task fails, and `ai lock release` without --agent drops someone else's lock. Ownership must be the only thing that decides staleness.

## Behavior

### Changed

- For `task-*` locks, staleness is decided only by the lease TTL (`staleAfterSeconds`), never by PID liveness. PID stays in the payload as a diagnostic field.
- `doctor`, `recover` and any health check call the same staleness predicate, so they cannot disagree with the claim gate.
- Re-acquiring a lock you already hold for the same agent and task refreshes `expires_at` and succeeds instead of returning "locked by <yourself>".
- `ai lock release` requires `--agent`; releasing a lock owned by another agent is refused with a message naming the owner. `--force` remains the operator escape hatch.

### Preserved

- File locks keep TTL + heartbeat semantics and the configured `staleAfterSeconds`.
- `--force` on release still works and still logs the action.
- Refusal messages keep their current tone and exit code 1.

## Acceptance criteria

- [ ] A task claimed by agent A stays A's after more than 30 seconds; a second agent's claim is refused and the branch/owner is unchanged
- [ ] ai doctor reports no stale lock for a live claim older than the PID liveness window
- [ ] ai recover proposes nothing for a live claim older than the PID liveness window
- [ ] Re-claiming the same task with the same agent succeeds, refreshes the lease, and does not duplicate locks
- [ ] ai lock release without --agent refuses with a message naming the current owner; --agent of another owner also refuses; --force still works
- [ ] Regression tests cover all four behaviors and pass
- [ ] Tests cover the new behavior and pass

## Out of scope

- Changing the default TTL values in `config/workspace.json`.
- Distributed locking or a database; the filesystem stays the source of truth.
- Rewriting the recover command beyond using the shared staleness predicate.

## Status

draft -> in progress -> shipped.
