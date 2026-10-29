---
status: shipped
task: 0001
approved_by: null
approved_on: null
---

# One-command first run

## Intent

A new developer currently runs `doctor`, `check`, `task new`, copies a spec
template, claims, sets up Git and starts a branch before the first edit. The
steps are individually correct but together they make the tool look heavier than
the work. The first successful task should cost one setup command and one claim.

The audience is a person trying the workspace on a small repository, plus the
agent that has to follow the same instructions. The change removes setup
commands, not safety checks.

## Behavior

### Changed

- `ai start` prepares the workspace and reports what it found:
  - creates missing runtime directories and `config/workspace.json`;
  - writes local adapter pointers and ignore rules when the workspace is a
    subfolder install, and reports that the root template needs no wiring;
  - runs `ai git setup` when a Git repository with a commit already exists, and
    otherwise reports `ai git setup` as the next step without prompting;
  - creates one starter task with a spec when the ledger is empty;
  - with `--agent <name>`, claims that task;
  - prints the two commands that begin the edit loop;
  - supports `--json` and `--no-demo`.
- `ai task new` creates the matching spec from `specs/TEMPLATE.md` and stores
  its path in the task `spec` field. An explicit `--spec` is linked but never
  rewritten. `--no-spec` keeps the old behavior.
- In `lite` mode `ai check` does not warn about a missing checkpoint until the
  task has been claimed longer than `handoff.warnAfterMinutes`. In `strict` mode
  the warning appears immediately. A stale checkpoint warns in both modes.
- `ai capabilities`, README, GUIDE and CHANGELOG mention the new entry point.

### Fixed

- `scripts/ai.cmd` returns the CLI exit code. A failing command no longer exits 0
  on Windows, so `ai check` and CI gates can fail correctly.

### Preserved

- `ai init`, `ai adopt`, `ai doctor`, `ai git setup` and `ai task new` keep their
  current behavior and flags.
- A live lease still refuses a claim. `ai start` never force-claims and never
  overwrites an existing task or spec.
- `ai check --strict` still exits non-zero for every warning that remains.
- No new dependency; Python 3.8+ and Git only.

## Acceptance criteria

- [x] In an empty root-template workspace with a Git commit, `ai start --json`
      exits 0, creates one task and one spec, and reports `shape: "root"` and
      the integration/production branches.
- [x] `ai start --agent me` claims the starter task and the printed next steps
      contain `ai git start`.
- [x] A second `ai start` creates no second task and exits 0.
- [x] With no Git commit, `ai start` exits 0, prints `ai git setup`, and does not
      wait for input.
- [x] `ai task new "X"` creates `specs/active/<id>-x.md`, sets `spec`, and the
      file has `task: <id>` in its front matter. `--no-spec` creates no file.
- [x] With `--spec specs/active/custom.md`, that file is linked and its content
      is unchanged.
- [x] `ai check --strict` on a just-claimed task in `lite` mode reports no
      missing-checkpoint warning; the same state in `strict` mode warns.
- [x] A checkpoint older than `handoff.warnAfterMinutes` warns in both modes.
- [x] `ai capabilities` lists `start`; README and GUIDE show it as the first
      command.
- [x] `scripts/ai.cmd` returns 1 for a failing command and 0 for a successful
      one.
- [x] `python -m unittest discover -s tests` passes.

## Out of scope

- Automatically creating a task branch during `start`.
- Interactive prompts beyond the existing `ai git setup` confirmation.
- Repairing broken workspaces; that is task `0002`.
- Changing Gitflow rules or the review requirement.

## Status

Shipped. Independently verified by `reviewer` on 2026-10-29:
`ai doctor --strict` 0 errors / 0 warnings, `ai check --strict` 0 errors /
0 warnings (13 tests), and `python -m unittest discover -s tests -v` passed
13/13. Every acceptance criterion was re-checked in a scratch copy.
