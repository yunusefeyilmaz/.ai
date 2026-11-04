---
id: 0002
title: "Existing-repo onboarding: adopt baseline commit, setup leaves HEAD on develop"
status: todo
owner: null
priority: high
spec: specs/active/0002-existing-repo-onboarding-adopt-baseline-commit-setup-leaves.md
depends_on: null
scope_allowed: "lib/config/adopt.py, lib/cmd/adopt.py, lib/cmd/git.py, lib/git/setup.py, lib/git/flow.py, lib/tests/test_onboarding.py"
scope_forbidden: null
locks: "lib/config/adopt.py, lib/cmd/adopt.py, lib/cmd/git.py, lib/git/setup.py, lib/git/flow.py, lib/tests/test_onboarding.py"
created: 2026-11-04T08:14:04Z
updated: 2026-11-04T08:14:04Z
lock: null
---

# 0002 - Existing-repo onboarding: adopt baseline commit, setup leaves HEAD on develop

## Intent

On an existing Git repo, `ai adopt` leaves .ai/ and .gitignore untracked, so the first `ai start` refuses with a dirty tree. `ai git setup` also leaves HEAD on production while develop starts behind it, which silently hides config/checks from feature branches and lets the review gate pass without running anything.

## Acceptance criteria

- [ ] After adopt on an existing Git repo, a single documented command commits the .ai/ and .gitignore baseline and leaves a clean working tree
- [ ] If the baseline cannot be committed automatically, the command prints the exact commands to run instead of silently leaving the tree dirty
- [ ] ai git setup ends with HEAD on the integration branch (develop)
- [ ] The integration branch contains every commit that existed on the production branch at setup time
- [ ] Tests reproduce the existing-repo flow and assert clean tree plus HEAD == develop
- [ ] Regression tests pass
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0002-existing-repo-onboarding-adopt-baseline-commit-setup-leaves.md`

<!-- Filled by the planner. -->

## Notes

## Log

- 2026-11-04T08:14:04Z | chief-1 | - -> todo | created
