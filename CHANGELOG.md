# Changelog

All notable changes to this workspace are documented here.

## [0.2.0] - 2026-10-27

### Added

- `GUIDE.md`: install, daily loop, command reference, context-budget playbook,
  multi-agent playbook, copy-paste prompts, troubleshooting and cheatsheet.
- `docs/orchestration.md`: roles, topologies, worktrees, lock ordering, review,
  git index contention, human gates, fleet monitoring and anti-patterns.
- `docs/recovery.md`: survival matrix, context-limit playbook, drift, interrupted
  sessions, corrupted files, git recovery and escalation.
- `ai adopt`: writes managed pointers to root `AGENTS.md`, `CLAUDE.md`,
  `.cursor/rules/ai-workspace.mdc` and `.github/copilot-instructions.md`, with
  `--check`, `--print`, `--ci` and `--force`.
- `ai checkpoint`, `ai handoff` and `ai resume`: resumable context with a JSON
  sidecar (git state + file fingerprints), checkpoint archive, handoff markers
  and a drift report.
- `ai recover [--apply]`: repairs owner/lock mismatches, done tasks outside
  `done/`, locks on done tasks, orphan locks, stale locks and orphan handoff
  markers.
- `ai git begin/end/verify`: coordinates the shared git index and verifies staged
  paths are covered by a held lock.
- `ai task block/unblock`, `depends_on` gating on claim, and `--json` output for
  `doctor`, `check`, `status`, `task list/show`, `lock status`, `resume`,
  `recover`, `artifact list`.
- `ai capabilities`: machine-readable CLI contract.
- `ai brief`: a paste-ready, self-contained context block for chat-only models
  (rules, task, spec, checkpoint, repo state, commands). Supports `--max-chars`
  and `--json`.
- Lock resources are repo-relative; **overlapping paths and globs conflict**.
  Acquisitions are serialized through a registry mutex.
- `config/workspace.json`: `locks.maxTtlSeconds`, `handoff`, `budget` and
  `security` sections.
- `ai check` now validates required docs, config keys, dependency ids, owner/lock
  consistency, checkpoint staleness, handoff freshness, orphan locks and
  secret-shaped tracked files.

### Changed

- `ai init --wire` now calls the same root-adapter logic as `ai adopt`.
- Checkpoint updates merge with the previous checkpoint instead of replacing
  omitted sections with placeholders.
- Assigning a task id no longer prints a spurious lock-release line.

## [0.1.0] - 2026-10-27

### Added

- Core workspace layout: `docs/`, `agents/`, `tasks/`, `specs/`, `prompts/`,
  `adapters/`, `scripts/`, `runtime/`.
- Cross-platform `ai` CLI (Python 3, stdlib only) with POSIX and Windows
  launchers: `init`, `doctor`, `check`, `status`, `task`, `lock`, `artifact`,
  `clean`, `version`.
- Atomic advisory locking with TTL, heartbeat and stale-lock detection.
- Race-safe task ids and an atomically claimed task store.
- Artifact quarantine with a watch list enforced by `ai check`.
- Role cards for orchestrator, planner, implementer, reviewer and QA.
- Tool adapters for Claude Code, Cursor, GitHub Copilot, Codex and generic agents.
- CI running `ai doctor --strict` and `ai check`.
