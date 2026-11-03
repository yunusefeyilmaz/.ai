---
id: 0019
title: "Gate CI on ruff, mypy and the capabilities contract"
status: review
owner: buffy-reviewer
priority: medium
spec: specs/active/0019-gate-ci-on-ruff-mypy-and-the-capabilities-contract.md
depends_on: "0016, 0017, 0018"
scope_allowed: ".github/workflows/ci.yml, pyproject.toml, lib/**, ai.py, requirements-dev.txt"
scope_forbidden: null
locks: ".github/workflows/ci.yml, pyproject.toml, lib/**, ai.py, requirements-dev.txt"
branch: feature/0019-gate-ci-on-ruff-mypy-and-the-capabilitie
created: 2026-11-03T09:12:54Z
updated: 2026-11-03T10:11:40Z
lock: task-0019
submitted_by: buffy-s4
---

# 0019 - Gate CI on ruff, mypy and the capabilities contract

## Intent

Lint-level defects (a duplicate definition, unused imports, a placeholder-less f-string) and contract drift all pass CI today because nothing checks them.

## Acceptance criteria

- [ ] CI runs ruff check, mypy and the existing capabilities consistency test as separate steps on every push and pull request
- [ ] ruff and mypy configuration lives in the repo so a contributor can run the same two commands locally, and the tree is clean under both
- [ ] the existing capabilities test is extended to fail when a parser flag is missing from ai capabilities and when a published command has no description
- [ ] a deliberately reintroduced duplicate definition or unused import fails the new gate (verified locally)
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0019-gate-ci-on-ruff-mypy-and-the-capabilities-contract.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-03T09:12:54Z | orchestrator | - -> todo | created
- 2026-11-03T09:52:54Z | buffy-s4 | todo -> in_progress | claimed
- 2026-11-03T09:52:55Z created branch feature/0019-gate-ci-on-ruff-mypy-and-the-capabilitie from develop by buffy-s4
- 2026-11-03T10:11:29Z committed: ci: gate CI on ruff, mypy and the capabilities contract
- 2026-11-03T10:11:35Z | buffy-s4 | in_progress -> review | submitted for independent review | check passed @215a808a by buffy-s4 (no commands)
- 2026-11-03T10:11:39Z | buffy-reviewer | review -> review | claimed
- 2026-11-03T10:11:40Z committed: chore: chore(0019): record the review handover
