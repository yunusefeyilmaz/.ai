---
id: 0007
title: "Docs truth pass and token diet"
status: todo
owner: null
priority: medium
spec: specs/active/0007-docs-truth-pass-and-token-diet.md
depends_on: "0001, 0002, 0003, 0005, 0004"
scope_allowed: "README.md, GUIDE.md, AGENTS.md, docs/**, prompts/**, lib/tests/test_docs.py"
scope_forbidden: null
locks: "README.md, GUIDE.md, AGENTS.md, docs/**, prompts/**, lib/tests/test_docs.py"
created: 2026-11-04T08:14:04Z
updated: 2026-11-04T08:14:04Z
lock: null
---

# 0007 - Docs truth pass and token diet

## Intent

README and GUIDE claim adopt ignores .ai/, AGENTS.md claims PID is diagnostic only, and a worker is told to read five documents before starting. Docs must match the code and fit a small context budget.

## Acceptance criteria

- [ ] README and GUIDE describe the actual ignore rules from lib/config/adopt.py
- [ ] AGENTS.md describes the actual lock staleness rule and fits within the token target (~70 lines)
- [ ] prompts/worker.md requires at most one document before the first command
- [ ] Every command shown in the docs exists and runs (doc test covers it)
- [ ] Doc tests pass
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0007-docs-truth-pass-and-token-diet.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-04T08:14:04Z | chief-1 | - -> todo | created
