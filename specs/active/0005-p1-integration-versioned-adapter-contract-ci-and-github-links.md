---
status: approved
task: 0005
approved_by: user
approved_on: 2026-10-29
---

# P1 integration: versioned adapter contract, CI and GitHub links

## Intent

Adding an agent or a CI provider should not require editing the core workflow. Pin the adapter surface, then connect external results to the task record.

## Behavior

### Versioned Adapter Contract

#### Changed

- `ai capabilities --json` publishes a versioned adapter contract including:
  - Command names the CLI exposes
  - Exit codes each command may return
  - State paths adapters may read/write (e.g. `runtime/state/`, `tasks/`, `specs/`)
  - Schema version of the contract (semver `major.minor.patch`)
- Add `adapters/contract.schema.json` defining the required shape of each `adapters/*/adapter.json`
- Each `adapters/*/adapter.json` gains an optional `version` field in semver format (`major.minor.patch`)
- When `version` is absent, tools treat it as `0.1.0`

#### Preserved

- Existing adapter.json fields (`tool`, `entry`, `autoload`, `supports`) remain unchanged
- Backward compatibility: adapters without version field continue to work
- No third-party dependencies

### Contract Test

#### Changed

- Add `tests/test_adapter_contract.py` that:
  - Reads every `adapters/*/adapter.json`
  - Validates each against `adapters/contract.schema.json`
  - Fails if any adapter references a command or flag the CLI no longer provides (checked against `ai capabilities --json` output)

#### Preserved

- Existing test suite in `tests/` continues to pass

### CI Result Recording

#### Changed

- `ai git commit --ci <url|result>` appends a CI result line to the task's log section:
  - Format: `CI: <result> at <url> (<UTC timestamp>)`
- `ai task show <id>` prints the CI result lines from the task log

#### Preserved

- Existing `ai git commit` behavior without `--ci` is unchanged

### GitHub Link Helpers

#### Changed

- Optional helper functions allow linking a GitHub issue and pull request from a task record
- These helpers work without a GitHub token when run locally (they only write to the task file)
- Link format in task notes: `GitHub: <issue-url> / <pr-url>`

#### Preserved

- No network calls are made by these helpers locally

### CI Matrix

#### Changed

- `.github/workflows/ci.yml` extended with a build matrix covering:
  - `ubuntu-latest`, `macos-latest`, `windows-latest`
  - Python 3.8, 3.11
- Each matrix job runs `ai doctor --strict` and `ai check`

#### Preserved

- Existing CI jobs on `ubuntu-latest` with Python 3.11 remain

## Acceptance criteria

- [ ] `ai capabilities --json` publishes a versioned adapter contract with command names, exit codes and state paths adapters may rely on
- [ ] A contract test fails when an adapter document references a command or flag the CLI no longer has
- [ ] `ai git commit --ci <url|result>` records the CI result in the task log; `ai task show` prints it
- [ ] Optional GitHub helpers link an issue and a pull request from the task without requiring a token to run locally
- [ ] Install/verify passes on Windows, macOS and Linux in CI
- [ ] `ai check --strict` passes

## Out of scope

- Uploading adapter contracts to external services
- Changing task/lock/checkpoint semantics
- Adding third-party CI/CD service dependencies
- Modifying existing adapter tool semantics beyond adding optional `version` field

## Status

Approved by user on 2026-10-29. Implementation ready.
