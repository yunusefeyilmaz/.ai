---
status: draft
task: 0004
approved_by: null
approved_on: null
---

# Make review a real git gate (branch, clean tree, HEAD) and fix rename parsing

## Intent

Review passes without checking the task branch or a clean product tree, then git finish fails after handover; git_state also mis-parses porcelain rename records, which would make such a gate unreliable.

## Behavior

### Changed

<!-- What will be different. Be concrete. -->

### Preserved

<!-- What must not change. Explicitly list existing behavior at risk. -->

## Acceptance criteria

- [ ] `python lib/tests/run.py test_review_gate` is green
- [ ] porcelain -z rename/copy records consume both paths and never create a phantom dirty entry
- [ ] review refuses when the current branch differs from the task branch, naming the mismatch and the next command
- [ ] review refuses when product files are uncommitted, listing them
- [ ] review refuses when recorded evidence belongs to another HEAD (when evidence exists)
- [ ] review still passes for a clean task branch, and for a workspace without Git
- [ ] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
