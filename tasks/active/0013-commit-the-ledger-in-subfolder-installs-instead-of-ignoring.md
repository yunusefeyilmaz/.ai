---
id: 0013
title: "Commit the ledger in subfolder installs instead of ignoring all of .ai/"
status: todo
owner: null
priority: high
spec: specs/active/0013-commit-the-ledger-in-subfolder-installs-instead-of-ignoring.md
depends_on: null
scope_allowed: "lib/config/adopt.py, lib/tests/test_adopt_ignore.py"
scope_forbidden: null
locks: "lib/config/adopt.py, lib/tests/test_adopt_ignore.py"
created: 2026-11-03T08:44:09Z
updated: 2026-11-03T08:44:09Z
lock: null
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
