---
status: draft
task: 0015
approved_by: null
approved_on: null
---

# Store setup answers explicitly in the tests that used --defaults

## Intent

Making `ai setup --defaults` a real human gate means the test suite can no longer use it as a non-interactive shortcut; those tests must state the answers they rely on.

## Behavior

### Changed

<!-- What will be different. Be concrete. -->

### Preserved

<!-- What must not change. Explicitly list existing behavior at risk. -->

## Acceptance criteria

- [ ] no test calls `ai setup --defaults` outside the gate's own tests
- [ ] the modules that previously relied on it are green
- [ ] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
