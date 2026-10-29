---
id: 0005
title: "P1 integration: versioned adapter contract, CI and GitHub links"
status: todo
owner: null
priority: medium
spec: null
created: 2026-10-29T06:55:08Z
updated: 2026-10-29T06:55:08Z
lock: null
depends_on: 0003
---

# 0005 - P1 integration: versioned adapter contract, CI and GitHub links

## Intent

Adding an agent or a CI provider should not require editing the core workflow.
Pin the adapter surface, then connect external results to the task record.

## Acceptance criteria

- [ ] `ai capabilities --json` publishes a versioned adapter contract with the
      command names, exit codes and state paths adapters may rely on.
- [ ] A contract test fails when an adapter document references a command or
      flag the CLI no longer has.
- [ ] `ai git commit --ci <url|result>` records the CI result in the task log;
      `ai task show` prints it.
- [ ] Optional GitHub helpers link an issue and a pull request from the task
      without requiring a token to run locally.
- [ ] Install/verify passes on Windows, macOS and Linux in CI.

## Plan

1. Freeze the contract and test it against `adapters/`.
2. Add `--ci` recording and the GitHub link fields.
3. Extend the workflow matrix per OS.

## Notes

## Log

- 2026-10-29T06:55:08Z created
