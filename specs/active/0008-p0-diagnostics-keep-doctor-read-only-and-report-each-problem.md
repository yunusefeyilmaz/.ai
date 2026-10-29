---
status: in progress
task: 0008
approved_by: null
approved_on: null
---

# Read-only diagnostics

## Intent

`ai doctor` is described as a reader and `--fix` as the writing path, but the
shared readers for locks and handoff markers call `ensure_dirs()`. A diagnostic
run therefore recreates empty runtime directories, which hides the missing-state
finding from a later `--fix` and contradicts the output.

The same review found a missing `config/workspace.json` reported twice: once by
the required-path loop with a `git checkout -- config/workspace.json` hint, and
once by the config loader with the correct `ai doctor --fix` hint. Only the
second one is true in a copied or ignored install.

One problem should produce one finding and one next step.

## Behavior

### Changed

- `list_locks` and `list_handoff_markers` take an `ensure` flag. CLI commands
  keep the default that creates directories; `collect_checks` passes `False`
  and returns an empty list when the directory is absent.
- `ai doctor` and `ai check` no longer create runtime state as a side effect.
  Only `--fix` writes.
- The required-path loop skips `config/workspace.json`; the config loader owns
  that finding and its `ai doctor --fix` hint.
- A missing framework file gets a shape-aware hint: `git checkout -- <path>` in
  a root install, and a restore from the `.ai` workspace copy in a subfolder
  install where the host repository may ignore it.

### Preserved

- `--fix` repairs the same set as 0.5.0: runtime directories and keep files, an
  absent config, and subfolder adapters and ignore rules.
- Exit codes, JSON keys and hint text for every other finding are unchanged.
- Lock, task and Git behavior outside diagnostics is unchanged.
- No new dependency.

## Acceptance criteria

- [ ] With `runtime/` removed, `ai doctor --json` exits 1, reports the missing
      path and leaves `runtime/` absent; `ai doctor --fix` recreates it.
- [ ] With `config/workspace.json` removed, exactly one finding contains
      `config/workspace.json` and its hint is `ai doctor --fix`.
- [ ] In a subfolder install with a deleted `docs/architecture.md`, the finding
      hint names the workspace copy and not host `git checkout`.
- [ ] `ai check --strict` still reports the same errors and warnings on the
      checkout, and the suite grows by the new regressions.
- [ ] `python -m unittest discover -s tests` passes.

## Out of scope

- Changing what `--fix` repairs.
- Making `ai recover` or `ai clean` read-only.
- New findings or new diagnostics.

## Status

In progress. Implementation and tests on the task branch.
