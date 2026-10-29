---
status: in progress
task: 0007
approved_by: null
approved_on: null
---

# Keep the start path branchable

## Intent

The first-run review proved a gap between the printed loop and reality. In a
root-template checkout, `ai start --agent me` writes a new task and spec, then
prints `ai git start`. That command refuses because the working tree is dirty.
The same report showed that a ledger with only archived tasks makes `start` aim
at a done task and exit 1.

A third, quieter defect surfaced while fixing the first: `git_state` reads
`git status --porcelain` through a helper that strips leading whitespace, so the
first line loses one character (`tasks/x` becomes `asks/x`). The staged-path
check can therefore report a covered path as uncovered.

## Behavior

### Changed

- `ai start` chooses among active tasks only. When none exist, it creates the
  starter task even if `tasks/done/` is populated.
- `ai git start` requires a clean product tree. Uncommitted changes under
  `tasks/` and `specs/` are ledger state and do not block branch creation; they
  travel with the branch and are committed with the task.
- `git status --porcelain` is parsed without trimming, so the first path is
  complete everywhere (dirty list, staged list, `ai git verify`).

### Preserved

- `ai git finish` still requires a clean tree; review and release metadata must
  be committed before a merge.
- A modified or untracked product file still blocks `ai git start`.
- Claim and branch rules are unchanged; no force path is added.
- `ai check` and task state semantics are unchanged.

## Acceptance criteria

- [ ] Fresh workspace: `ai start --agent me`, then `ai git start --task <id>
      --agent me --type feature` creates the branch and exits 0 while the task
      and spec are still uncommitted.
- [ ] The same sequence exits 1 with a clear message when `src/app.py` is
      untracked.
- [ ] A ledger holding only a done task yields a new active task with the next
      id, claimed by the requested agent, and exit 0.
- [ ] An active task makes `start` reuse it and create nothing.
- [ ] With `README.md` staged as the first porcelain entry and leased,
      `ai git verify --strict` reports every staged path covered.
- [ ] The suite covers these cases; `ai check --strict` is green.

## Out of scope

- Relaxing `ai git finish`, which must still see committed review metadata.
- Auto-committing ledger files during `start`.
- The transient launcher message reported once during review; it could not be
  reproduced and all exit-code tests pass.

## Status

In progress. Implementation and tests on the task branch.
