---
status: draft
task: 0008
approved_by: null
approved_on: null
---

# Share one evidence state machine between resume, review and status

## Intent

`task_status` calls a partial check valid while `task_green` rejects it, so `ai resume` promises proof that review then refuses.

## Behavior

### Changed

- `evidence.evaluate(task_id, head, since_iso=None)` is the single state machine and returns `none`, `invalidated`, `failed`, `partial`, `stale` or `green` plus its record, summary and reason.
- `task_status` returns that state and `task_green` returns `(state == "green", reason-or-summary)`, so resume, review, history and doctor read the same verdict.
- A `--fast` or `--no-commands` record is `partial` everywhere; `ai resume` labels it as insufficient for review instead of valid.

### Preserved

- The wording and priority of invalidated, failed, stale and green messages stay the same.
- Claim-time freshness still applies to review and done (`task_green` with `since_iso`), not to a plain status read.
- Missing evidence still reports `none`.

## Acceptance criteria

- [ ] `python lib/tests/run.py test_evidence_state` is green
- [ ] one state function returns none, invalidated, failed, partial, stale or green
- [ ] `task_status` and `task_green` use that function and never disagree for the same head and claim time
- [ ] a `--fast` or `--no-commands` record reports `partial`, and `ai resume` labels it as insufficient for review
- [ ] green, failed, stale and invalidated keep their current messages
- [ ] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
