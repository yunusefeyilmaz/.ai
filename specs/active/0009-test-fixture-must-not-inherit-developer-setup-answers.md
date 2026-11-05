---
status: draft
task: 0009
approved_by: null
approved_on: null
---

# Test fixture must not inherit developer setup answers

## Intent

`make_workspace` copies the repository config and neutralizes a few keys, but it
left `workflow.requireCheck` alone. After a contributor runs `ai setup --set
checks=yes`, that key becomes `true`, so every throwaway workspace suddenly
demands project checks it does not have and review-based tests fail. The suite
must give the same result regardless of what the developer answered during
onboarding.

## Behavior

### Changed

- `make_workspace` pins `workflow.requireCheck` back to its mode-driven default
  (`"strict"`), so lite workspaces do not require checks and strict workspaces do.
- The same pin lands in every fixture that copies the repository config, so no
  test module inherits the developer's `ai setup` answer.
- A regression test proves the fixture ignores a `checks=yes` config copied from
  the developer's checkout.

### Preserved

- Existing fixture overrides (`checks: []`, `chiefOnlyTasks: false`,
  `requireSpec: false`) keep their current effect.
- Tests that deliberately enable checks in strict mode keep working.

## Acceptance criteria

- [x] Every test fixture pins `workflow.requireCheck` to "strict" instead of inheriting the developer's `ai setup` answer
- [x] A regression test copies a config with `requireCheck: true` and asserts the fixture workspace does not require checks in lite mode
- [x] The existing suite passes after `ai setup --set checks=yes` in the developer checkout
- [x] Tests cover the new behavior and pass

## Out of scope

- Changing how `ai setup` writes preferences.
- Isolating every config key; only the one that changes gate behavior is pinned.

## Status

draft -> in progress -> shipped.
