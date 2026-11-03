---
status: draft
task: 0014
approved_by: null
approved_on: null
---

# Make ai setup --defaults a real human gate

## Intent

`ai setup --defaults` accepts the recommended answers in one non-interactive command, so an agent can fake the chief's required human approval.

## Behavior

### Changed

<!-- What will be different. Be concrete. -->

### Preserved

<!-- What must not change. Explicitly list existing behavior at risk. -->

## Acceptance criteria

- [ ] `ai setup --defaults` without `--yes` is refused
- [ ] `ai setup --defaults` requires an interactive terminal
- [ ] task creation is still refused while preferences are unconfirmed
- [ ] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
