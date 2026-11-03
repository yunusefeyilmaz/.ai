---
status: draft
task: 0011
approved_by: null
approved_on: null
---

# Derive the capabilities contract from the argparse parser

## Intent

`ai capabilities` is hand-maintained, so it silently misses real flags (`ai check --task/--agent/--no-commands`) and machine-readable clients get a contract that disagrees with the parser.

## Behavior

### Changed

<!-- What will be different. Be concrete. -->

### Preserved

<!-- What must not change. Explicitly list existing behavior at risk. -->

## Acceptance criteria

- [ ] every command the parser defines appears in `ai capabilities` output
- [ ] every option string each command defines appears in the published flags for that command
- [ ] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
