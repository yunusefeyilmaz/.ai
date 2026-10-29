# Changelog

All notable changes to this workspace are documented here.

## [0.5.2] - 2026-10-29

### Added

- `ai metrics [--json] [--since <date>]` summarizes task completion and review
  times, lock refusals, retries, resumes, and event counts by agent from a
  local, date-rotated JSONL ledger.
- Task lifecycle, lock refusal, checkpoint, and resume commands append local
  events. The ledger is not uploaded and historical tasks are not backfilled.

## [0.5.1] - 2026-10-29

### Fixed

- `ai doctor` and `ai check` no longer create runtime directories while
  diagnosing; only `--fix` writes. A missing state tree now stays visible until
  it is repaired on purpose.
- A missing `config/workspace.json` produces one finding with the
  `ai doctor --fix` hint instead of a duplicate `git checkout` hint.
- Missing framework files in a subfolder install are hinted as a restore from
  the `.ai` copy rather than a host-repository checkout that cannot work.

## [0.5.0] - 2026-10-29

### Added

- `ai doctor --fix`: repairs only missing, regenerable state - runtime
  directories and keep files, an absent `config/workspace.json`, and missing
  subfolder adapter pointers and ignore rules. Each change is reported as
  `FIXED`; task, spec, lock and Git data are never touched.
- Every diagnostic carries a repair hint. Human output prints `fix: <command>`;
  `--json` adds a `findings` array of `{level, message, hint}` and a `fixes`
  array. With `--fix` the exit code is 0 only when nothing remains.
- Subfolder installs now report missing root adapter pointers and ignore rules,
  so the repair is visible before an agent fails to find the workspace.
- `tests/test_doctor.py`: regression coverage for hinted findings, safe repair,
  corrupt config, orphan locks and subfolder wiring.

### Changed

- `ai doctor --json` keeps `ok`, `errors` and `warnings` and adds structured
  findings, so existing scripts keep working.
- `ai init` shares its placeholder logic with `--fix`; behavior is unchanged.

## [0.4.0] - 2026-10-29

### Added

- `ai start`: prepares missing state, detects the install shape and Git layout,
  runs `ai git setup` when a commit already exists, creates one starter task
  with its spec and, with `--agent`, claims it. It never prompts, force-claims or
  overwrites a task.
- `ai task new` writes `specs/active/<id>-<slug>.md` from `specs/TEMPLATE.md`
  and links it in the task. `--no-spec` keeps the previous behavior.
- `tests/`: first CLI integration tests for first-run, spec creation and the
  lite checkpoint rule. They run in `ai check`.
- `docs/roadmap.md` and tasks `0001`-`0006`: the P0-P2 plan with success
  signals and guardrails.

### Changed

- In `lite` mode `ai check` gives a freshly claimed task
  `handoff.warnAfterMinutes` before warning about a missing checkpoint. `strict`
  mode still warns immediately; a stale checkpoint warns in both modes.
- `ai start` considers active tasks only: a ledger of archived tasks receives a
  new starter task instead of a failed attempt to claim a done one.
- `ai git start` ignores uncommitted `tasks/` and `specs/` files; product changes
  still block the branch. This makes the printed first-run loop work without a
  manual metadata commit.
- `ai task new` no longer prints a stray `Released 'tasks.index'.` line.
- `scripts/ai.cmd` now exits with the CLI's code; previously every Windows run
  reported success, hiding failed checks from CI and scripts.
- `git status --porcelain` parsing no longer drops the first character of the
  first entry, so `ai git verify` sees every staged path in full.
- README, GUIDE and the CLI contract open with `ai start`.

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
- `ai task ready` (todo, dependencies done, no live lease) and
  `ai task next --agent <name>` (atomic claim of the best ready task).
- `prompts/orchestrator.md` and `prompts/worker.md`: two-window plan/build
  prompts. The orchestrator creates tasks, specs and dependencies; workers only
  consume the ready queue.
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
