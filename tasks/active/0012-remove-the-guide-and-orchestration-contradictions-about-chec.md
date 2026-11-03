---
id: 0012
title: "Remove the GUIDE and orchestration contradictions about checks and review claims"
status: review
owner: null
priority: medium
spec: specs/active/0012-remove-the-guide-and-orchestration-contradictions-about-chec.md
depends_on: null
scope_allowed: "GUIDE.md, docs/orchestration.md"
scope_forbidden: null
locks: "GUIDE.md, docs/orchestration.md"
branch: feature/0012-remove-the-guide-and-orchestration-contr
created: 2026-11-03T08:44:09Z
updated: 2026-11-03T08:56:38Z
lock: null
submitted_by: buffy-s3
---

# 0012 - Remove the GUIDE and orchestration contradictions about checks and review claims

## Intent

GUIDE and docs/orchestration.md describe behavior the code no longer has, so an agent that reads them follows the wrong rule.

## Acceptance criteria

- [ ] GUIDE states that `ai check --strict --task` records per-task evidence
- [ ] docs/orchestration.md says the reviewer claims the task before writing a verdict
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0012-remove-the-guide-and-orchestration-contradictions-about-chec.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T08:44:09Z | orchestrator | - -> todo | created
- 2026-11-03T08:55:40Z | buffy-s3 | todo -> in_progress | claimed
- 2026-11-03T08:55:41Z created branch feature/0012-remove-the-guide-and-orchestration-contr from develop by buffy-s3
- 2026-11-03T08:55:45Z committed: docs: state the check evidence and reviewer claim rules the code enforces
- 2026-11-03T08:56:38Z | buffy-s3 | in_progress -> review | submitted for independent review | check passed @f1783141 by buffy-s3 (no commands)
