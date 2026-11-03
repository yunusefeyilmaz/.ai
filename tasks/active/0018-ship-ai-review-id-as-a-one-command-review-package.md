---
id: 0018
title: "Ship ai review <id> as a one-command review package"
status: todo
owner: null
priority: high
spec: specs/active/0018-ship-ai-review-id-as-a-one-command-review-package.md
depends_on: null
scope_allowed: "lib/cmd/review.py, ai.py, lib/git/repo.py, lib/tests/test_review_package.py, AGENTS.md, GUIDE.md, docs/**"
scope_forbidden: null
locks: "lib/cmd/review.py, ai.py, lib/git/repo.py, lib/tests/test_review_package.py, AGENTS.md, GUIDE.md, docs/**"
created: 2026-11-03T09:12:54Z
updated: 2026-11-03T09:12:54Z
lock: null
---

# 0018 - Ship ai review <id> as a one-command review package

## Intent

A reviewer currently has to hunt the spec, the criteria, the diff, the check evidence and the history across five commands, which is both slow and easy to do partially.

## Acceptance criteria

- [ ] ai review <id> prints one package containing task state, the linked spec with its acceptance criteria, the branch diff against the integration branch, the recorded check evidence and the transition history
- [ ] the package ends with a short checklist naming what the reviewer must verify, and a failing/missing evidence record is called out explicitly
- [ ] --stat limits the diff to a summary and --max-lines N truncates the full diff with a visible marker; --json returns the same data structured
- [ ] the command is read-only: it claims nothing, writes nothing and exits 1 with an actionable message for an unknown task id
- [ ] the new command is registered, described in ai capabilities and listed in AGENTS.md and the review docs
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0018-ship-ai-review-id-as-a-one-command-review-package.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T09:12:54Z | orchestrator | - -> todo | created
