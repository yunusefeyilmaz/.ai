---
status: approved
task: 0019
approved_by: orchestrator
approved_on: 2026-11-03
---

# Gate CI on ruff, mypy and the capabilities contract

## Intent

CI runs `doctor`, `check` and the self-tests, and nothing else, so lint-level defects (a duplicate `cmd_git_setup`, unused imports, a placeholder-less f-string) and contract drift pass. Any one of them is cheap to catch with a tool and expensive to catch in review.

## Behavior

### Changed

- New `pyproject.toml` carrying `[tool.ruff]` (line length, target version, selected rule families, per-file ignores for the test harness) and `[tool.mypy]` (`python_version`, `ignore_missing_imports`, no strict-everything), so a contributor runs the exact same two commands locally.
- `.github/workflows/ci.yml` gains three steps after the existing ones: `ruff check .` (or the configured target), `mypy` over `lib` and `ai.py`, and the capabilities consistency test as an explicitly named step.
- `lib/tests/test_capabilities.py` gains two assertions: every parser flag appears in `ai capabilities` (already present, kept) and every published top-level command has a description that is not the generic `--help` fallback.
- The tree is brought clean under both tools: the duplicate definition, the placeholder-less f-string and the unused imports the report names are removed.

### Preserved

- The existing CI matrix (three OSes, 3.8/3.11) and the three existing steps.
- Stdlib-only runtime: ruff and mypy are development tools, installed in CI only, and are not imported by any `lib/` module.
- `python lib/tests/run.py` remains the single test entry point.

## Acceptance criteria

- [ ] CI runs `ruff check`, `mypy` and the existing capabilities consistency test as separate steps on every push and pull request
- [ ] ruff and mypy configuration lives in the repo so a contributor can run the same two commands locally, and the tree is clean under both
- [ ] the existing capabilities test is extended to fail when a parser flag is missing from `ai capabilities` and when a published command has no description
- [ ] a deliberately reintroduced duplicate definition or unused import fails the new gate (verified locally)
- [ ] Tests cover the new behavior and pass

## Out of scope

- Reformatting the whole tree with `ruff format`/black.
- Adding type annotations everywhere; mypy runs leniently.
- Pinning exact tool versions in a lockfile.

## Status

shipped when green.
