---
status: shipped
task: 0004
approved_by: reviewer
approved_on: 2026-11-03
---

# Make review a real git gate (branch, clean tree, HEAD) and fix rename parsing

## Intent

Review passes without checking the task branch or a clean product tree, then git finish fails after handover; git_state also mis-parses porcelain rename records, which would make such a gate unreliable.

## Behavior

### Changed

- `ai task review` refuses before handover when Git is on and the task's checkout is not mergeable: the current branch differs from the task branch, the product tree has uncommitted changes, or the task has no commit yet. The message names the offending state and the command that fixes it.
- Review also refuses when recorded verification evidence belongs to a different HEAD than the current one, so the reviewer never approves a commit that was not checked.
- Workspace ledger paths (`tasks/`, `specs/`) stay exempt from the clean-tree rule: the review/claim bookkeeping is itself written during handover.
- `git status --porcelain -z` parsing consumes the old path of rename and copy records, so `git_state()` no longer reports a phantom dirty file for a staged rename.

### Preserved

- Workspaces without a Git repository (or with Git disabled in config) still review normally.
- A clean task branch passes review unchanged, and `ai git finish` keeps its own dirty-tree guard as the last line of defence.
- Ledger-only changes never block review.

## Acceptance criteria

- [x] `python lib/tests/run.py test_review_gate` is green
- [x] porcelain -z rename/copy records consume both paths and never create a phantom dirty entry
- [x] review refuses when the current branch differs from the task branch, naming the mismatch and the next command
- [x] review refuses when product files are uncommitted, listing them
- [x] review refuses when recorded evidence belongs to another HEAD (when evidence exists)
- [x] review still passes for a clean task branch, and for a workspace without Git
- [x] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
