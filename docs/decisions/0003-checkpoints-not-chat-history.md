# 0003 - Resume from checkpoints, not chat history

- Status: accepted
- Date: 2026-10-27
- Deciders: project maintainers

## Context

Agent sessions end for ordinary reasons: the context window fills, a process is
killed, a rate limit hits, a human closes a terminal. Chat history is not durable,
not portable across tools, and often not available to the next session. Work that
exists only in that history is lost or, worse, silently re-done.

## Decision

Make context exhaustion a first-class state:

- `ai checkpoint` writes a structured snapshot (objective, status, done,
  in-progress step, next steps, decisions, do-not list, files, verification) plus
  a JSON sidecar with git state and file fingerprints.
- `ai handoff` refreshes the checkpoint and writes a marker for another session.
- `ai resume` prints the snapshot, a **drift report** against the real repository,
  and a ready-to-paste prompt.
- `ai check` warns when in-progress work has no checkpoint or the checkpoint is
  stale.

A checkpoint is written for a stranger. It is not a transcript.

## Consequences

- Losing a context window costs minutes, not the task.
- Drift is explicit; the next agent re-verifies changed files before trusting the
  plan.
- Checkpoints stay in `runtime/` and are never committed; tasks and specs remain
  the durable record.
- Writers must summarize, not dump. Secrets must never be checkpointed.

## Alternatives

- **Rely on chat replay.** Not portable, not durable, and usually unavailable
  after a crash.
- **Commit full transcripts.** Bloats history, leaks secrets, and does not help a
  different tool.
- **No checkpoint, reconstruct with `git diff` only.** Works for code, loses
  intent, decisions and open questions.
