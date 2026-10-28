---
status: approved
task: 0001
approved_by: null
approved_on: null
---

# Gitflow setup must use a commit-backed base

## Intent

Prevent Gitflow setup from using an unborn branch name as a production base or
leaving a newly initialized repository on a different branch from the
configured production branch.

## Behavior

### Changed

- Initialize new repositories directly on the configured production branch
  when supported, with a safe fallback for older Git versions.
- Choose existing production bases by resolved commit object IDs, not by
  unverified symbolic branch names.
- If an unborn repository has no commit-backed local branches, follow the
  existing interactive baseline confirmation flow without creating a branch
  from `master` or `main` by name.

### Preserved

- Existing committed repositories keep their commit history.
- Initial project files are not staged or committed until explicit confirmation.
- Configured production and integration branch names remain customizable.

## Acceptance criteria

- [x] A fresh `git init` uses the configured production branch as `HEAD` where
  the installed Git supports `--initial-branch`.
- [x] An unborn `master` or `main` is never selected as a commit base.
- [x] Setup creates missing base branches from a commit object ID.
- [x] A configured production or integration ref that exists without a commit
  produces a clear repair message instead of attempting to use its name as a
  branch base.
- [x] A new empty repo creates the initial production commit only after the
  existing explicit confirmation.
- [x] `ai check --strict` passes.

## Out of scope

- Changing remote branches or pushing any branch.
- Renaming existing committed branches.

## Status

Implemented and independently reviewed. The exact unborn repository branch
creation case was reviewed statically, not exercised in a separate test repo.
