---
id: 0002
title: "Existing-repo onboarding: adopt baseline commit, setup leaves HEAD on develop"
status: review
owner: reviewer-opencode
priority: high
spec: specs/active/0002-existing-repo-onboarding-adopt-baseline-commit-setup-leaves.md
depends_on: null
scope_allowed: "lib/config/adopt.py, lib/cmd/adopt.py, lib/cmd/git.py, lib/git/setup.py, lib/git/flow.py, lib/tests/test_onboarding.py, lib/tests/test_worktree.py"
scope_forbidden: null
locks: "lib/config/adopt.py, lib/cmd/adopt.py, lib/cmd/git.py, lib/git/setup.py, lib/git/flow.py, lib/tests/test_onboarding.py, lib/tests/test_worktree.py"
branch: null
created: 2026-11-04T08:14:04Z
updated: 2026-11-05T11:34:33Z
lock: task-0002
submitted_by: opencode-1
merged_into: develop
merged_at: 2026-11-05T11:34:33Z
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
- 2026-11-05T09:52:49Z | opencode-1 | todo -> in_progress | claimed
- 2026-11-05T09:52:50Z | opencode-1 | in_progress -> todo | claim rolled back | the task branch could not start
- 2026-11-05T09:53:25Z | opencode-1 | todo -> in_progress | claimed
- 2026-11-05T09:53:27Z created branch feature/0002-existing-repo-onboarding-adopt-baseline from develop by opencode-1
- 2026-11-05T10:13:58Z committed: feat: commit the workspace baseline and land setup on the integration branch
- 2026-11-05T10:35:48Z committed: test: adapt the host-worktree test to the committed workspace baseline
- 2026-11-05T10:55:37Z checkpoint by opencode-1 (checkpoint, ?%)
- 2026-11-05T11:08:56Z | opencode-1 | in_progress -> review | submitted for independent review | check passed @47344545 by opencode-1 (tests passed, ruff passed, mypy passed)
- 2026-11-05T11:17:41Z | reviewer-opencode | review -> review | claimed
- 2026-11-05T11:23:34Z committed: chore: record the review claim for task 0002
- 2026-11-05T11:34:33Z merged feature/0002-existing-repo-onboarding-adopt-baseline into develop by reviewer-opencode
