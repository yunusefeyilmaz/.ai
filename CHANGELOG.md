# Changelog

All notable changes to this workspace are documented here.

## [0.8.0] - 2026-10-31

### Added

- **Transition history.** Every state change is a structured line in the task
  (`<time> | <actor> | <from> -> <to> | <reason> | <proof>`); `ai history <id>`
  [`--evidence`, `--json`] reads it.
- **Per-task verification evidence.** `ai check --task <id> --agent <n>` records
  commands, exit codes, agent and commit in `runtime/state/evidence/<id>.jsonl`.
  The strict-mode review gate now requires green, full evidence for that task on
  the current HEAD (new commits make it stale); `ai resume` reports whether
  recorded evidence is still valid. Replaces the global `last-check` gate.
- **`changes_requested` status** and `ai task request-changes <id> --agent <r>
  --reason ...` (reviewer only, never the submitter). The task becomes ready for
  rework; `ai now` points the producer at it.
- **Task scope.** `ai task new --allow GLOB --forbid GLOB`; `ai git commit`
  refuses staged paths outside it and `ai git verify --task <id>` reports them.
- **Roles.** Optional `team` (agent -> roles) and `roles` in
  `config/workspace.json` guard `task.new/claim/review/request_changes/done` and
  `git.finish`; `policy.unknownAgent` is `allow` or `deny`. Default: no table,
  everything allowed.
- A reviewer claiming a task in `review` no longer flips it back to `in_progress`.

- **Chief flow.** `ai setup` stores the user's choices in `config/workspace.json`
  (review, checks, git, tests, continue, workers; `--check NAME=COMMAND`,
  `--defaults`). `ai plan apply plan.json` creates many linked tasks at once
  (dependencies, `locks`, scope, intent, acceptance), validating cycles and
  unknown keys first and warning about overlapping locks between unordered tasks.
  `ai now` on a new project says `ai setup`, then `ai plan apply`.
- **One-command worker.** `ai task claim|next` also takes the task's declared
  file locks (all or nothing) and, when Git is enabled, opens the task branch.
  `ai task review` runs the project checks itself when verification is required,
  records the evidence, frees the file locks and prints `STOP` unless
  `workflow.autoContinue` is on (the worker waits for the user).
- **Reviewer flow.** `ai task next --review` claims the oldest task waiting for
  review (never the reviewer's own); `ai now --role implementer|reviewer|chief`
  tailors the recommendation.
- Required verification with no configured project checks is now a hard error at
  review (not a free pass). `git.enabled=false` turns the Git steps off.
- Forced lock takeovers are recorded as `lock_forced` events; forced `done`
  records `forced` and `submitted_by` in the event log and the task history.
- `config/` and `docs/decisions/` no longer count as product changes when
  starting a task branch. Checkpoint age and `now --json` (`schema: 1`) read
  their values from config / carry a schema version.

- **Per-task Git worktrees** (`git.isolation = worktree`, set by
  `ai setup --set workers=N`, N > 1). `ai task claim|next` creates
  `.ai/worktrees/<branch>/` from `develop`; coordination state stays in the single
  main workspace. `ai git commit|verify`, `ai check --task`, `ai checkpoint|handoff|resume`
  and `ai task review` operate in the task's worktree automatically. `ai git finish`
  verifies there, merges in the main checkout, then removes the worktree and branch.
  New `ai worktree list|path|prune`; `ai doctor` warns about orphans. The worktrees
  folder and briefing files are excluded via `info/exclude`, so no checkout is dirtied.
  A briefing (`AGENTS.md`/`CLAUDE.md`) with the absolute CLI path is written into each
  worktree.
- `ai git finish` ignores ledger changes (tasks, specs, config) when checking that
  the main tree is clean.

## [0.7.0] - 2026-10-30

### Changed

- **Restructure.** The 4,800-line `scripts/ai.py` is split into `lib/`, which
  holds scripts only: `lib/{core,config,runtime,tasks,specs,git,decisions,cmd,tests}`.
  `ai.py` is now a thin entry point at the workspace root (launchers `ai` and
  `ai.cmd` moved with it). Data stays where it was: `tasks/`, `specs/`,
  `runtime/`, `config/`, `templates/git/`, `docs/decisions/`. See `lib/README.md`.
  Command behavior is unchanged.
- Commands are auto-discovered from `lib/cmd/*.py` (and future
  `skills/*/skill.py`); adding a command is one file.
- `ai.py` keeps bytecode out of the workspace (cached under the system temp
  dir) and imports only the module of the invoked command: ~100 ms -> ~45 ms
  per call.
- `python lib/tests/run.py` runs the test modules in parallel (one process per
  module, `-j N`); `unittest discover` still works serially.

### Added

- `ai now [--agent <n>]`: ~10 lines with the state and the single next required
  command (derived from task status, Git, checkpoints and the last check).
- `ai context`: compact project memory (open work with next steps, shipped
  work, ADRs, recent activity).
- `ai decision new|list`: numbered ADRs in `docs/decisions/`.
- Workflow gates (`lib/tasks/gates.py`): `ai task done` requires the task to be
  in `review` and approved by a different agent than the submitter
  (`submitted_by` / `reviewed_by` are recorded). In strict mode `ai task review`
  requires a green full `ai check` recorded after the claim. Configure with
  `workflow.requireReview` and `workflow.requireCheck` in
  `config/workspace.json`. `--force` bypasses and is logged.
- `ai check` records its result in `runtime/state/last-check.json`.

### Fixed

- `ai check` no longer runs the workspace's own test suite. The shipped
  `config/workspace.json` has an empty `checks` list; projects add their own
  test/lint commands. With no checks configured, `ai check` prints a note on
  stderr. The workspace's self-tests run via `python lib/tests/run.py` (and in
  this repository's CI).
- Agent docs no longer tell agents to run `ai check --strict` (CI-only flag).

- The generated board no longer writes a mojibake dash for done tasks.

### Migration

Move `scripts/ai*` to the workspace root, add `lib/`, and move the old
`tests/` into `lib/tests/`. Remove the old `cli tests` entry from `checks` in
`config/workspace.json` (the workspace's own tests no longer belong there). Re-run
`ai adopt --force` in host projects to refresh the pointer blocks.

## [0.6.0] - 2026-10-29

### Added

- `ai status --board`: a read-only one-screen view. Active tasks are listed in
  dependency order with id, status, owner, priority, checkpoint age, waiting
  reason and title, followed by every lease with its TTL, remaining seconds and
  `held`/`stale` state, and the last five refused leases.
- A refused lease names its conflict: `ai lock acquire` and a refused task claim
  record `conflict` and `conflict_agent` on the `lock_refused` event.
  `ai lock status --json` adds `state`, `remaining_seconds` and the matching
  `refusals` to each lease. Events written before this release render as
  `conflict unknown`.
- Versioned adapter contract: `adapters/contract.schema.json` fixes the shape
  of every `adapters/*/adapter.json`, each adapter may carry a semver
  `version` (absent means `0.1.0`), and `ai capabilities --json` publishes
  `adapter_contract` with the contract version, schema path and the state paths
  adapters may rely on.
- `tests/test_adapter_contract.py`: every adapter is validated against the
  schema, and adapter documents may only reference commands the CLI publishes.
- `ai git commit --ci <url|result>` records the CI result in the task log and
  `ai task show` prints the recorded CI results.
- `ai task link --issue <url> --pr <url>` links a GitHub issue and pull request
  from a task record. It writes only to the task file and needs no token.
- `.github/workflows/ci.yml` now runs on Ubuntu, macOS and Windows with Python
  3.8 and 3.11.
- `tests/test_board.py`: snapshot coverage for empty, single-task, blocked and
  dependency-ordered boards, plus lease detail, read-only and plain-text
  guarantees.

### Changed

- `ai status` keeps its previous output in every respect; `--board` is additive
  and `--json` is unchanged.
- `ai check --strict` stays the single verification gate; reliability tests for
  concurrent leases, lease takeover and guarded Git failures run inside it.

## [0.5.2] - 2026-10-29

### Added

- `ai metrics [--json] [--since <date>]` summarizes task completion and review
  times, lock refusals, retries, resumes, and event counts by agent from a
  local, date-rotated JSONL ledger.
- Task lifecycle, lock refusal, checkpoint, and resume commands append local
  events. The ledger is not uploaded and historical tasks are not backfilled.

## [0.5.1] - 2026-10-29

### Fixed

- `ai check` no longer runs the workspace's own test suite. The shipped
  `config/workspace.json` has an empty `checks` list; projects add their own
  test/lint commands. With no checks configured, `ai check` prints a note on
  stderr. The workspace's self-tests run via `python lib/tests/run.py` (and in
  this repository's CI).
- Agent docs no longer tell agents to run `ai check --strict` (CI-only flag).

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
