---
id: 0003
title: "P0 reliability: concurrency, lease and recovery test suite"
status: done
owner: null
priority: high
spec: specs/active/0003-p0-reliability-concurrency-lease-and-recovery-test-suite.md
created: 2026-10-29T06:55:08Z
updated: 2026-10-29T08:14:45Z
lock: null
depends_on: 0002
branch: null
merged_into: develop
merged_at: 2026-10-29T08:14:44Z
---

# 0003 - P0 reliability: concurrency, lease and recovery test suite

## Intent

The README claims atomic claims, TTL leases, recovery and guarded merges. Those
claims are currently verified by hand. An automated suite makes them testable
and keeps later changes from breaking them.

## Acceptance criteria

- [ ] A stdlib `unittest` suite covers: concurrent acquisition of one resource
      (exactly one winner), expired-lease takeover, the previous owner returning
      after expiry, `recover --apply` on owner/lock drift, dirty index and
      conflicting staging, and a failed `git finish` leaving branches intact.
- [ ] A file lease such as `project` can be acquired while a task lease is held;
      the task namespace never blocks file leases.
- [ ] Every test builds its own temporary workspace, runs the real CLI, needs no
      network and finishes in under 60 seconds.
- [ ] `ai check --fast` runs the suite; failures name the scenario.
- [ ] The porcelain first-entry regression test fails against the old parser
      (`tasks/BOARD.md` must not become `asks/BOARD.md`); a test that also passes
      on the broken base does not count.

## Plan

1. Add a shared fixture that copies the framework into a temp directory.
2. Cover leases and recovery first, then Git contention and merge failure.
3. Register the suite as a fast check.

## Notes

Known gaps from the 0007 review: the staged-path parser test does not fail on the
old parser, and `test_product_changes_still_block_the_branch` uses a
non-idempotent `mkdir` that would break if the checkout gains a top-level
`src/`. Fold both fixes into this task.

Spec and plan approved by user on 2026-10-29.

## Log

- 2026-10-29T06:55:08Z created
- 2026-10-29T08:06:28Z claimed by codex
- 2026-10-29T08:06:45Z created branch chore/0003-p0-reliability-concurrency-lease-and-rec from develop by codex
- 2026-10-29 implementation ready: `ai check --fast` -> 32 tests passed in 46.3 seconds; 0 errors, 0 warnings.
- 2026-10-29T08:12:12Z committed: chore(task): archive completed task 0008
- 2026-10-29T08:12:32Z committed: test(reliability): cover lease recovery and guarded git failures
- 2026-10-29T08:12:42Z submitted for independent review by codex
- 2026-10-29T08:12:42Z released by codex
- 2026-10-29T08:12:54Z committed: chore(task): record review handoff for 0003
- 2026-10-29T08:14:44Z merged chore/0003-p0-reliability-concurrency-lease-and-rec into develop by reviewer
- 2026-10-29T08:14:45Z marked done by reviewer
