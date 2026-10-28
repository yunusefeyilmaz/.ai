---
status: approved
task: 0001
approved_by: null
approved_on: null
---

# Detect unborn HEAD correctly

## Intent

Git can print the literal `HEAD` from `git rev-parse HEAD` in an unborn
repository even though the command failed. The workspace must not interpret
that text as a commit and attempt to create a production branch from it.

## Behavior

### Changed

- Store `git_state().head` only when Git successfully resolves `HEAD` to a
  commit object.
- Let setup route repositories without a commit to the existing baseline
  confirmation flow, regardless of whether their unborn branch is named
  `master`, `main`, or a configured production name.

### Preserved

- Existing commits and configured production branch names remain unchanged.
- No files are committed without the existing explicit baseline confirmation.

## Acceptance criteria

- [x] `git_state()` reports no head when `rev-parse HEAD` fails or returns an
  unresolved symbolic name.
- [x] In an unborn repository, setup does not pass `HEAD` as a branch base.
- [x] Setup uses the configured production branch and reaches baseline
  confirmation when there is no commit-backed branch.
- [x] `ai check --strict` passes.

## Out of scope

- Changing production/integration branch configuration.
- Automatically creating an initial project commit.

## Status

Implemented and independently reviewed; `ai check --strict` passes. The unborn
checkout behavior was reviewed from control flow; no isolated repository test
was run.
