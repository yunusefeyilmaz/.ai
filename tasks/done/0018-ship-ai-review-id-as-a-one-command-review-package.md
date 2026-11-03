---
id: 0018
title: "Ship ai review <id> as a one-command review package"
status: done
owner: buffy-reviewer
priority: high
spec: specs/done/0018-ship-ai-review-id-as-a-one-command-review-package.md
depends_on: null
scope_allowed: "lib/cmd/review.py, lib/cmd/capabilities.py, lib/specs/spec.py, ai.py, lib/git/repo.py, lib/tests/test_review_package.py, AGENTS.md, GUIDE.md, docs/**"
scope_forbidden: null
locks: "lib/cmd/review.py, lib/cmd/capabilities.py, lib/specs/spec.py, ai.py, lib/git/repo.py, lib/tests/test_review_package.py, AGENTS.md, GUIDE.md, docs/**"
branch: null
created: 2026-11-03T09:12:54Z
updated: 2026-11-03T09:52:46Z
lock: null
submitted_by: buffy-s4
merged_into: develop
merged_at: 2026-11-03T09:52:45Z
reviewed_by: buffy-reviewer
reviewed_at: 2026-11-03T09:52:46Z
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
- 2026-11-03T09:46:23Z | buffy-s4 | todo -> in_progress | claimed
- 2026-11-03T09:46:24Z created branch feature/0018-ship-ai-review-id-as-a-one-command-revie from develop by buffy-s4
- 2026-11-03T09:52:28Z committed: feat: add ai review, the one-command review package
- 2026-11-03T09:52:38Z | buffy-s4 | in_progress -> review | submitted for independent review | check passed @3b890834 by buffy-s4 (no commands)
- 2026-11-03T09:52:38Z | buffy-reviewer | review -> review | claimed
- 2026-11-03T09:52:39Z committed: chore: chore(0018): record the review handover
- 2026-11-03T09:52:45Z merged feature/0018-ship-ai-review-id-as-a-one-command-revie into develop by buffy-reviewer
- 2026-11-03T09:52:46Z | buffy-reviewer | review -> done | approved | check passed @26344af6 by buffy-reviewer (no commands)
