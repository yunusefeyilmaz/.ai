---
id: 0012
title: "Remove the GUIDE and orchestration contradictions about checks and review claims"
status: todo
owner: null
priority: medium
spec: specs/active/0012-remove-the-guide-and-orchestration-contradictions-about-chec.md
depends_on: null
scope_allowed: "GUIDE.md, docs/orchestration.md"
scope_forbidden: null
locks: "GUIDE.md, docs/orchestration.md"
created: 2026-11-03T08:44:09Z
updated: 2026-11-03T08:44:09Z
lock: null
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
