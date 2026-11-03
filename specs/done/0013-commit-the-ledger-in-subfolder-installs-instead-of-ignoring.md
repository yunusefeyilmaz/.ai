---
status: draft
task: 0013
approved_by: null
approved_on: null
---

# Commit the ledger in subfolder installs instead of ignoring all of .ai/

## Intent

`ai adopt` writes `.ai/` into the host `.gitignore`, so a subfolder install never commits tasks, specs or decisions even though the product promises durable project memory.

## Behavior

### Changed

<!-- What will be different. Be concrete. -->

### Preserved

<!-- What must not change. Explicitly list existing behavior at risk. -->

## Acceptance criteria

- [ ] `ai adopt` ignores only ephemeral workspace paths and keeps the ledger committable
- [ ] a blanket `.ai/` ignore line already present is migrated away
- [ ] `ai adopt --check` passes once the migration ran
- [ ] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
