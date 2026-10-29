---
status: approved
task: 0003
approved_by: user
approved_on: 2026-10-29
---

# P0 reliability: concurrency, lease and recovery test suite

## Intent

The workspace documents atomic resource claims, expiring leases, recovery, and
guarded Git merges, but key failure modes are only checked manually. A fast,
network-free test suite should make these guarantees reproducible in isolated
temporary workspaces and catch regressions before changes are merged.

## Behavior

### Changed

- Add stdlib `unittest` coverage that invokes the real CLI in a fresh copied
  workspace for each scenario.
- Cover concurrent acquisition with exactly one winner, expired lease takeover,
  rejection of a previous owner after takeover, owner/lock drift repair,
  simultaneous task and file leases, dirty index and conflicting staged paths,
  and failed `git finish` preserving branches.
- Correct the porcelain first-entry regression so it fails with the old parser
  that dropped the first character from `tasks/BOARD.md`.
- Make `test_product_changes_still_block_the_branch` robust when `src/` already
  exists.
- Register the suite as a fast `ai check` command with scenario-specific
  failure messages.

### Preserved

- Tests use only the Python standard library and local Git; they do not access
  the network or mutate the source checkout.
- Existing CLI behavior and unrelated tests remain unchanged.

## Acceptance criteria

- [ ] Every listed concurrency, lease, recovery, staging, and merge scenario is
      covered by an independent test with a descriptive failure name.
- [ ] A file lease can be acquired while a task lease is held.
- [ ] The staged-path first-entry regression fails when run against the old
      parser and passes against the corrected parser.
- [ ] Each scenario creates an isolated temporary workspace, uses the real CLI,
      and the complete suite finishes in under 60 seconds without network access.
- [ ] `ai check --fast` runs the suite and reports a failing scenario clearly.
- [ ] Existing tests pass.

## Out of scope

- Changing the lease, recovery, or Git workflow implementation beyond fixes
  needed to satisfy the regression coverage.
- Adding third-party test dependencies or network-backed tests.

## Status

Approved by user on 2026-10-29. Implementation is ready for independent review.
