---
status: draft
task: 0005
approved_by: null
approved_on: null
---

# Require the reviewer to claim a task before requesting changes

## Intent

Any agent can currently send any task in review back, which breaks the one-task-one-owner invariant and lets an observer disrupt delivery.

## Behavior

### Changed

<!-- What will be different. Be concrete. -->

### Preserved

<!-- What must not change. Explicitly list existing behavior at risk. -->

## Acceptance criteria

- [ ] `python lib/tests/run.py test_request_changes` is green
- [ ] request-changes by an agent without the live review claim is refused with the claiming command in the message
- [ ] a reviewer that claimed the task with `ai task next --review` can still request changes
- [ ] the submitter and non-review states keep their existing refusals
- [ ] existing suite expectations are updated only where the new claim requirement applies
- [ ] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
