---
id: 0013
title: "Commit the ledger in subfolder installs instead of ignoring all of .ai/"
status: review
owner: null
priority: high
spec: specs/active/0013-commit-the-ledger-in-subfolder-installs-instead-of-ignoring.md
depends_on: null
scope_allowed: "lib/config/adopt.py, lib/tests/test_adopt_ignore.py"
scope_forbidden: null
locks: "lib/config/adopt.py, lib/tests/test_adopt_ignore.py"
branch: null
created: 2026-11-03T08:44:09Z
updated: 2026-11-03T08:57:57Z
lock: null
submitted_by: buffy-s3
merged_into: develop
merged_at: 2026-11-03T08:57:57Z
---

# 0013 - Commit the ledger in subfolder installs instead of ignoring all of .ai/

## Intent

`ai adopt` writes `.ai/` into the host `.gitignore`, so a subfolder install never commits tasks, specs or decisions even though the product promises durable project memory.

## Acceptance criteria

- [ ] `ai adopt` ignores only ephemeral workspace paths and keeps the ledger committable
- [ ] a blanket `.ai/` ignore line already present is migrated away
- [ ] `ai adopt --check` passes once the migration ran
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0013-commit-the-ledger-in-subfolder-installs-instead-of-ignoring.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T08:44:09Z | orchestrator | - -> todo | created
- 2026-11-03T08:57:13Z | buffy-s3 | todo -> in_progress | claimed
- 2026-11-03T08:57:14Z created branch feature/0013-commit-the-ledger-in-subfolder-installs from develop by buffy-s3
- 2026-11-03T08:57:53Z committed: fix: commit the ledger in subfolder installs instead of ignoring all of .ai/
- 2026-11-03T08:57:55Z | buffy-s3 | in_progress -> review | submitted for independent review | check passed @2f61ae0b by buffy-s3 (no commands)
- 2026-11-03T08:57:57Z merged feature/0013-commit-the-ledger-in-subfolder-installs into develop by buffy-reviewer
