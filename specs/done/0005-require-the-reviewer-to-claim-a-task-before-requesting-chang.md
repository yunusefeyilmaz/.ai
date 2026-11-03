---
status: shipped
task: 0005
approved_by: reviewer
approved_on: 2026-11-03
---

# Require the reviewer to claim a task before requesting changes

## Intent

Any agent can currently send any task in review back, which breaks the one-task-one-owner invariant and lets an observer disrupt delivery.

## Behavior

### Changed

- `ai task request-changes` now requires the reviewer to hold the live review claim on the task. A task in `review` with no owner is refused with the claiming command (`ai task next --review --agent <agent>` or `ai task claim <id> --agent <agent>`); a task already claimed by another reviewer is refused by naming that reviewer and how to hand it over.
- Requesting changes releases the reviewer's claim together with the task lock, so the producer can reclaim immediately.

### Preserved

- Only tasks in `review` can receive a change request.
- The producer (`submitted_by`) still may not request changes on its own work, and that refusal keeps priority.
- Role policy (`task.request_changes`) is still checked first, so an implementer is refused for its role.
- The producer reclaims the task with `ai task claim <id>` exactly as before.

## Acceptance criteria

- [x] `python lib/tests/run.py test_request_changes` is green
- [x] request-changes by an agent without the live review claim is refused with the claiming command in the message
- [x] a reviewer that claimed the task with `ai task next --review` can still request changes
- [x] the submitter and non-review states keep their existing refusals
- [x] existing suite expectations are updated only where the new claim requirement applies
- [x] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
