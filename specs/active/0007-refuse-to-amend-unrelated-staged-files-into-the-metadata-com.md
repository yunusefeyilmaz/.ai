---
status: draft
task: 0007
approved_by: null
approved_on: null
---

# Refuse to amend unrelated staged files into the metadata commit

## Intent

`commit_task_metadata` runs `git commit --amend` whenever anything is staged, so files the user staged earlier silently join the previous commit.

## Behavior

### Changed

- `commit_task_metadata(..., amend=True)` computes the expected ledger paths (task file + board) and compares them with the staged paths before amending.
- If any other path is staged, the amend is skipped, a warning names the unexpected paths, and those changes stay staged: no unrelated file joins the previous commit.
- The staged-path comparison is exposed as a small helper so it can be tested without a full commit.

### Preserved

- The amend stays the default for the ledger follow-up of `ai git commit`.
- `amend=False` still creates a new commit with the provided message.
- Metadata failures still land in the event log through `_metadata_failure`, and a nothing-to-commit case stays silent.

## Acceptance criteria

- [ ] `python lib/tests/run.py test_metadata_commit` is green
- [ ] the amend runs only when the staged paths are exactly the task file and the board
- [ ] an unrelated staged path makes the amend skip with a warning that names the path, and leaves it staged
- [ ] the non-amend path still creates a commit with the given message
- [ ] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
