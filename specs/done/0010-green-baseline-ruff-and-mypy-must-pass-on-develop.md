---
status: draft
task: 0010
approved_by: null
approved_on: null
---

# Green baseline: ruff and mypy must pass on develop

## Intent

A v1.0.0 release cannot start from a red baseline. `develop` currently fails the
project's own gates: `python -m ruff check .` reports three import-order errors
and `python -m mypy` reports nineteen errors, all in `lib/ui/` (the most recent
commit). Every task that runs `ai check` inherits this failure, so nothing can be
delivered until it is fixed.

## Behavior

### Changed

- `python -m ruff check .` exits 0 on the repository.
- `python -m mypy` exits 0 on Windows **and** with `--platform linux`, since CI
  lints on Linux and some `lib/ui` errors are platform-specific.
- Type fixes stay inside `lib/ui/`: annotations for empty collections, real
  types for the values that flow through `demo.py`, a correct terminal guard for
  `termios`, and the missing `get_provider` reference in `screens/base.py`.
- If a rule genuinely cannot hold for a file, the exclusion is written in
  `pyproject.toml` with a reason (no blanket `# type: ignore`).

### Preserved

- The UI's behavior and screen layout are unchanged; only typing and imports move.
- `lib/ui` stays importable on Python 3.8 (CI matrix) and on Windows.

## Acceptance criteria

- [ ] `python -m ruff check .` exits 0
- [ ] `python -m mypy` exits 0 on Windows
- [ ] `python -m mypy --platform linux` exits 0 (what CI evaluates)
- [ ] `python lib/tests/run.py` is green, including the UI tests
- [ ] `python ai.py check --strict` is green on the release commit

## Out of scope

- Redesigning or removing the TUI.
- Touching files outside `lib/ui/` and `pyproject.toml`.
- Raising mypy strictness beyond the current configuration.

## Status

draft -> in progress -> shipped.
