---
id: 0008
title: "Release v1.0.0: version bump, changelog, release checklist"
status: todo
owner: null
priority: high
spec: specs/active/0008-release-v1-0-0-version-bump-changelog-release-checklist.md
depends_on: "0006, 0007"
scope_allowed: "VERSION, lib/core/paths.py, CHANGELOG.md"
scope_forbidden: null
locks: "VERSION, lib/core/paths.py, CHANGELOG.md"
created: 2026-11-04T08:14:04Z
updated: 2026-11-04T08:14:04Z
lock: null
---

# 0008 - Release v1.0.0: version bump, changelog, release checklist

## Intent

Ship the first release whose claims are true: bump version, record the changelog, and prove the gates green.

## Acceptance criteria

- [ ] VERSION and lib/core/paths.py both report 1.0.0
- [ ] CHANGELOG has a 1.0.0 entry that states there are no new features, only reliability fixes, and lists the lock semantics change
- [ ] ai version prints 1.0.0
- [ ] ai doctor --strict and the full check suite are green on the release commit
- [ ] Release notes mention the 0.9.9 to 1.0.0 upgrade note for lock semantics
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0008-release-v1-0-0-version-bump-changelog-release-checklist.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-04T08:14:04Z | chief-1 | - -> todo | created
