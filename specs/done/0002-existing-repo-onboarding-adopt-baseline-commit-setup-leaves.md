---
status: draft
task: 0002
approved_by: null
approved_on: null
---

# Existing-repo onboarding: adopt baseline commit, setup leaves HEAD on develop

## Intent

On an existing Git repo, `ai adopt` leaves .ai/ and .gitignore untracked, so the first `ai start` refuses with a dirty tree. `ai git setup` also leaves HEAD on production while develop starts behind it, which silently hides config/checks from feature branches and lets the review gate pass without running anything.

## Behavior

### Changed

- `ai adopt` (or the setup step it points to) commits the `.ai/` and `.gitignore` baseline in one commit on the integration branch, leaving a clean working tree.
- When the commit cannot be made automatically (no Git, no identity, user declined), the command prints the exact commands to run and exits non-zero instead of pretending success.
- `ai git setup` ends with HEAD on `develop`, and `develop` starts at the production branch's current HEAD so no existing commit is missing from feature branches.

### Preserved

- Ignore rules stay as implemented: only `.ai/runtime/`, `.ai/worktrees/` and adapter output are ignored; the rest of `.ai/` is tracked.
- Product files are never committed automatically; only the workspace baseline is.
- Gitflow branch names and the configured integration/production branches are unchanged.

## Acceptance criteria

- [ ] After adopt on an existing Git repo, a single documented command commits the .ai/ and .gitignore baseline and leaves a clean working tree
- [ ] If the baseline cannot be committed automatically, the command prints the exact commands to run instead of silently leaving the tree dirty
- [ ] ai git setup ends with HEAD on the integration branch (develop)
- [ ] The integration branch contains every commit that existed on the production branch at setup time
- [ ] Tests reproduce the existing-repo flow and assert clean tree plus HEAD == develop
- [ ] Regression tests pass
- [ ] Tests cover the new behavior and pass

## Out of scope

- Changing the `.ai/` ignore policy itself.
- Supporting non-Git projects in this task.
- Auto-pushing to a remote.

## Status

draft -> in progress -> shipped.
