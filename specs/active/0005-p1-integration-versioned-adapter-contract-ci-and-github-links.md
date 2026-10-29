---
status: in progress
task: 0005
approved_by: null
approved_on: null
---

# P1 integration: versioned adapter contract, CI and GitHub links

## Intent

The workspace has multiple adapters (claude-code, codex, cursor, github-copilot, generic) each with their own `adapter.json` configuration. This spec establishes a versioned adapter contract framework that provides:

- A consistent version format for adapter configurations
- CI workflow integration to validate adapter contracts on changes
- GitHub task integration to record `merged_into` and `merged_at` when adapter contracts are merged
- A mechanism for tracking adapter contract changes through the lifecycle

## Behavior

### Versioned Adapter Contract

#### Changed

- Add `adapter.json` version field supporting semver format (`major.minor.patch`)
- When adapter JSON is modified, append `adapter_contract_updated` event to `runtime/state/events.jsonl` with:
  - UTC timestamp
  - event name: `adapter_contract_updated`
  - tool name from adapter.json `tool` field
  - version from adapter.json `version` field (if present, otherwise "0.1.0")
- CI workflow must validate adapter contract version consistency across all adapters
- If version is missing from adapter.json, default to `0.1.0` and append `adapter_contract_version_default` event

#### Preserved

- Existing adapter.json fields and structure remain unchanged
- Adapter tool, entry, autoload, and supports fields are preserved
- Backward compatibility: adapters without version field continue to work

### CI Integration

#### Changed

- Update `.github/workflows/ci.yml` to include adapter contract validation step
- Add step: `ai validate-adapter-contracts` that:
  - Reads all `adapters/*/adapter.json` files
  - Validates each has required fields: `tool`, `entry`, `autoload`, `supports`
  - Checks version field consistency (if present, must be valid semver)
  - Fails the workflow if any contract is invalid
- Add step: `ai record-adapter-metrics` that records adapter usage metrics

#### Preserved

- Existing CI steps (doctor, check) remain unchanged
- Workflow runs on push and pull_request

### GitHub Task Integration

#### Changed

- When adapter contract PR is merged, record `merged_into` and `merged_at` on the task
- Append `task_merged` event to `runtime/state/events.jsonl` with:
  - UTC timestamp
  - event name: `task_merged`
  - task ID being merged
  - source branch/target branch information
  - adapter contract version(s) merged
- The `merged_into` field on the task record should point to the GitHub PR number or branch
- The `merged_at` field should contain the UTC timestamp of the merge

#### Preserved

- Existing task lifecycle events (creation, claim, review, release) remain unchanged
- Lock contention and refusal events are preserved

### Acceptance criteria

- [ ] `adapters/*/adapter.json` files include optional `version` field in semver format
- [ ] `ai validate-adapter-contracts` command validates all adapter contracts and fails on invalid ones
- [ ] `ai record-adapter-metrics` command records adapter usage metrics
- [ ] CI workflow includes adapter contract validation step that fails on invalid contracts
- [ ] When adapter contract PR is merged, `merged_into` and `merged_at` are recorded on the task
- [ ] `task_merged` event is appended to `runtime/state/events.jsonl` with correct fields
- [ ] `ai check --strict` passes
- [ ] Reading metrics with no ledger is read-only, reports zero counts, and returns null for duration medians with no samples

### Out of scope

- Uploading adapter contracts to external services
- Changing task/lock/checkpoint semantics
- Adding third-party CI/CD service dependencies
- Modifying existing adapter tool semantics

## Status

In progress. Implementation and tests on the task branch.
