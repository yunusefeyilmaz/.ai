---
status: approved
task: 0003
approved_by: null
approved_on: null
---

# Reliable Gitflow bootstrap

## Intent

Make Gitflow setup work both when `.ai` is installed inside a host project and
when this repository is used directly as the project. Handle unborn symbolic
branches without treating their names as commit-backed refs.

## Behavior

### Changed

- Resolve the project root to the workspace itself when it is a Git checkout;
  otherwise preserve the `.ai` subfolder installation behavior.
- When setup finds no commit-backed local branch, select the configured
  production branch and request the existing explicit baseline confirmation.
- Never try to create the production branch from an unborn branch name.

### Preserved

- Existing committed repositories retain their history and branch content.
- Initial project files remain unstaged and uncommitted until the operator
  confirms the displayed baseline.
- Safe-directory errors remain explicit and limited to the exact checkout.

## Acceptance criteria

- [x] In a direct checkout where the workspace root is the Git root, project
  operations and Git setup target that checkout rather than its parent.
- [x] Running `ai adopt` in a `.ai` subfolder targets the host project even
  before the host has `.git` or `.gitignore`.
- [x] In an unborn repository with `HEAD` symbolically pointing to `master`,
  setup does not attempt `git branch main master`; it follows the explicit
  baseline confirmation flow and then creates configured base branches.
- [x] In a committed repository with another current branch, setup creates
  missing configured base branches from a valid commit.
- [x] Existing adapter installation behavior for `.ai` subfolder installs is
  preserved.

## Out of scope

- Automatically committing project files without interactive confirmation.
- Changing Gitflow branch names or merge policy.

## Status

Implemented; `ai check --strict` passes and independent review passed. The
unborn-branch confirmation path was reviewed statically, not exercised here.
