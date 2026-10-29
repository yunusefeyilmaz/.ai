---
id: 0005
title: "P1 integration: versioned adapter contract, CI and GitHub links"
status: in_progress
owner: implementer
priority: medium
spec: specs/active/0005-p1-integration-versioned-adapter-contract-ci-and-github-links.md
created: 2026-10-29T06:55:08Z
updated: 2026-10-29T11:57:56Z
lock: task-0005
depends_on: 0003
branch: feature/0005-p1-integration-versioned-adapter-contrac
---

# 0005 - P1 integration: versioned adapter contract, CI and GitHub links

## Intent

Adding an agent or a CI provider should not require editing the core workflow.
Pin the adapter surface, then connect external results to the task record.

## Acceptance criteria

- [x] `ai capabilities --json` publishes a versioned adapter contract with the
      command names, exit codes and state paths adapters may rely on.
- [x] A contract test fails when an adapter document references a command or
      flag the CLI no longer has.
- [x] `ai git commit --ci <url|result>` records the CI result in the task log;
      `ai task show` prints it.
- [x] Optional GitHub helpers link an issue and a pull request from the task
      without requiring a token to run locally.
- [x] Install/verify passes on Windows, macOS and Linux in CI.

## Plan

1. Freeze the contract and test it against `adapters/`.
2. Add `--ci` recording and the GitHub link fields.
3. Extend the workflow matrix per OS.

## Notes

- Adapter contract schema frozen at `adapters/contract.schema.json`.
- Adapter docs command validation covered in `tests/test_adapter_contract.py`.
- `ai task show` formats CI results.
- `link_task_github` and `ai task link` provide tokenless local GitHub issue/PR linking.

## Log

- 2026-10-29T06:55:08Z created
- 2026-10-29T08:56:58Z claimed by cline
- 2026-10-29T08:57:07Z created branch feature/0005-p1-integration-versioned-adapter-contrac from develop by cline
- 2026-10-29T11:30:00Z spec aligned to task acceptance criteria, approved by user
- 2026-10-29T11:30:00Z added `adapters/contract.schema.json` for adapter.json validation
- 2026-10-29T11:30:00Z added optional `version` field (0.1.0) to all 5 adapter.json files
- 2026-10-29T11:30:00Z extended `ai capabilities --json` with `adapter_contract` section
- 2026-10-29T11:30:00Z added `--ci` flag to `ai git commit` for CI result recording
- 2026-10-29T11:30:00Z created `tests/test_adapter_contract.py` (4 tests passing)
- 2026-10-29T11:30:00Z extended `.github/workflows/ci.yml` with OS/Python matrix
- 2026-10-29T09:05:18Z committed: feat(adapters): add versioned adapter contract and CI matrix
- 2026-10-29T09:06:55Z submitted for independent review by cline
- 2026-10-29T09:06:57Z released by cline
- 2026-10-29T11:40:36Z claimed by implementer
- 2026-10-29T11:51:00Z completed CI result formatting in task show, GitHub link helpers, and adapter command contract tests
- 2026-10-29T11:57:56Z committed: feat(adapters): format CI results in task show, add GitHub helpers and adapter doc tests
