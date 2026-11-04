---
status: draft
task: 0004
approved_by: null
approved_on: null
---

# No silent green: fail loudly when the project has no checks

## Intent

`ai check` looks successful when the project has no checks configured, and a review can pass on that empty evidence. An empty gate must be visible, not silent.

## Behavior

### Changed

- `ai check` exits non-zero with an actionable message when `checks` is empty.
- An explicit flag (for example `--allow-empty`) opts out for projects that intentionally run no checks, and the output says so.
- In strict mode, `ai task review` refuses to pass on an empty check result.

### Preserved

- Running configured checks, their ordering, timeouts and evidence recording stay unchanged.
- `ai check --task ... --agent ...` still records provenance for the task.
- Lite mode may still allow a documented opt-out.

## Acceptance criteria

- [ ] `ai check` exits non-zero with an actionable message when no project checks are configured
- [ ] An explicit opt-out (or documented flag) exists for projects that intentionally run no checks, and it is printed in the output
- [ ] `ai task review` cannot pass on an empty check result in strict mode
- [ ] Regression tests cover both the refusal and the opt-out
- [ ] Tests cover the new behavior and pass

## Out of scope

- Adding new check types or a plugin system.
- Changing how check evidence is stored.

## Status

draft -> in progress -> shipped.
