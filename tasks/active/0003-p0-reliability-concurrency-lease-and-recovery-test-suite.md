---
id: 0003
title: "P0 reliability: concurrency, lease and recovery test suite"
status: todo
owner: null
priority: high
spec: null
created: 2026-10-29T06:55:08Z
updated: 2026-10-29T06:55:08Z
lock: null
depends_on: 0002
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

## Plan

1. Add a shared fixture that copies the framework into a temp directory.
2. Cover leases and recovery first, then Git contention and merge failure.
3. Register the suite as a fast check.

## Notes

## Log

- 2026-10-29T06:55:08Z created
