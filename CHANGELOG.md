# Changelog

All notable changes to this workspace are documented here.

## [0.9.8] - 2026-11-03

### Added

- **`ai review <id>` — read-only review package.** Prints the task state, the linked
  spec with its acceptance criteria, the branch diff against the integration branch
  (with `--stat` and `--max-lines`), the recorded check evidence, the transition
  history and a final checklist. `--json` returns the same content structured.
  (`lib/cmd/review.py`, `docs/task-flow.md`, `GUIDE.md`, `AGENTS.md`)
- **`ai now --json` gains the machine contract.** Top-level `schema: 2` plus
  `needs_human` (bool), `question` (string|null), `next_args` (argv, ready to
  execute) and `blocker` (string|null). `next_args` is concrete for the caller's
  own agent and derives from the same text the printed NEXT line prints.
  (`lib/runtime/overview.py`, `lib/cmd/now.py`, `lib/tests/test_now_json.py`)
- **Semantic `ai doctor` audits.** (1) active tasks whose spec is missing, unreadable
  or still the template while `workflow.requireSpec` is on; (2) dependency cycles
  among active tasks as an error naming the cycle; (3) `in_progress`/`blocked` tasks
  without an owner; (4) `in_progress`/`review` tasks without a branch once the
  Gitflow base exists. New tests: `lib/tests/test_doctor_semantics.py`.
  (`lib/runtime/health.py`, `lib/specs/spec.py`)

### Changed

- **`ai capabilities` is a faithful contract.** The published command descriptions
  are derived from the parser, every parser flag is published per command, every
  published command has a real description (no `--help` fallback), and the new
  `ai review` command appears in the contract. (`lib/cmd/capabilities.py`,
  `lib/tests/test_capabilities.py`, `pyproject.toml`)
- **Repository-local lint and type gates.** `pyproject.toml` (ruff select:
  E4/E7/E9/F/W/I/B, 120-char lines) and `[tool.mypy]` (3.9, `ignore_missing_imports`)
  land in the repo; `requirements-dev.txt` installs them for contributors and CI.
  (`pyproject.toml`, `requirements-dev.txt`)

### Fixed

- **CI now gates every push and pull request on ruff, mypy and the capabilities
  contract, in addition to `ai doctor --strict`, `ai check --strict` and
  `python lib/tests/run.py`.** (`.github/workflows/ci.yml`)
- A deliberately reintroduced duplicate definition and an unused import both fail
  the new ruff/mypy gates (verified locally). (`lib/cmd/version.py`)

### Notes

- The repository uses a managed `config/workspace.json` as a template: its
  shipped `confirmed: false` keeps `ai task new` a chief-only, user-confirmed step.
  Engineers who want `ai setup --set review=yes checks=yes git=yes tests=yes
continue=no workers=1 --check "tests=python lib/tests/run.py"` for their own
  checkout should copy it rather than commit one install's answers here.

## [0.9.7] - 2026-11-02

### Fixed

- **`ai task show` crashed on a legacy console codepage.** Printing a task body
  containing a character the console/pipe encoding cannot represent (for example
  `→` under cp1254) raised `UnicodeEncodeError` after the useful state had been
  printed. `ai.py` now configures its streams once at startup: a real terminal
  keeps its codepage and escapes the characters it cannot show (`\u2192`), while
  redirected output (editor task output, CI, a pipe) is written as UTF-8. The
  same guard covers every command that prints task titles, quotes or specs.
  (`lib/core/console.py`, `ai.py`)

- **A checkpoint can no longer be split from its sidecar without a repair.**
  `checkpoint.md` and its `.json` sidecar are two writes; a crash between them is
  now detected by `ai recover` (`rebuild checkpoint sidecar <id>`) and repaired
  with `--apply`, taking the Markdown as authoritative and marking the rebuilt
  sidecar `rebuilt: true`.
  (`lib/runtime/checkpoints.py`, `lib/cmd/recover.py`)

### Added

- Encoding regressions: a redirected cp1254 stream is written as UTF-8, a cp1254
  terminal escapes what it cannot encode, and an end-to-end `ai task show` with
  `PYTHONIOENCODING=cp1254` succeeds and prints the arrow. Plus the
  checkpoint-sidecar repair test.
  (`lib/tests/test_platform.py`, `lib/tests/test_regressions.py`)

## [0.9.6] - 2026-11-02

### Changed

- **Task transitions have one implementation.** `lib/tasks/transition.py` owns the
  guarded sequence every state change repeated by hand: re-find the task under
  `workspace_state_guard()`, refuse when the file moved, re-parse, apply, write
  and refresh the board. `review`, `request-changes`, `block`, `unblock` and
  `done` now pass a `mutate` callback (and, for `done`, a `finalize` that archives
  the file) instead of copying the block; a refusal can no longer half-apply.
  `lib/cmd/task.py` keeps argument handling and printed messages.
  (`lib/tasks/transition.py`, `lib/cmd/task.py`)

- **Shared rendering and scope checks.** `ai task list`, `ai task ready` and
  `ai status` print through one `board.text_table()`, and `ai git commit` /
  `ai git verify` compute scope violations through one
  `scope.staged_violations()` so the two commands cannot drift.
  (`lib/tasks/board.py`, `lib/tasks/scope.py`, `lib/git/flow.py`, `lib/cmd/git.py`)

- `adapter.json`'s `supports` field is documented for what it is: the usage modes
  a wiring enables, not shipped hooks or permission integrations.
  (`adapters/README.md`)

### Added

- `lib/tests/test_platform.py`: fault injection at the `fsio` / `repo` boundary —
  a failed `fsync` keeps the previous content and leaves no temp debris, a
  Windows sharing violation is retried until it succeeds, a missing `git`
  returns 127, a git timeout returns 124, and a CRLF task file parses and
  round-trips to LF. These run on every OS instead of skipping off Windows.

## [0.9.5] - 2026-11-02

### Fixed

- **`ai task discard` reported the wrong refusal.** The mandatory-terminal guard ran
  before the lease checks, so a task held by another agent produced "Discard requires
  an interactive terminal" instead of naming the holder, and no test could reach the
  lock path. The holder is now reported first; the smoke test asserts the message.
  (`lib/cmd/task.py`, `lib/tests/test_commands_smoke.py`)

- **Scope matching stripped characters instead of normalizing paths.** `matches()`
  used `lstrip("./")`, a character strip, so `../escape.py` became `escape.py` and
  matched an allowed `src/**` glob while `src/../src/a` was judged by raw string
  comparison. Both scope checks and lease overlap now normalize lexically through
  `normalize_rel_path`, and a path escaping the repository never matches.
  (`lib/tasks/scope.py`)

- **`ai git commit` made the documented refusal opt-in.** AGENTS.md promises that
  staged paths without a held lease are refused, but the check only ran with
  `--verify`. It now runs automatically when the task declares `locks` or
  `scope_allowed`; ledger paths (`tasks/`, `specs/`, `config/`, `docs/decisions/`)
  never need a lease, and `--no-verify` is the explicit, visible bypass.
  (`lib/git/flow.py`, `lib/git/repo.py`, `lib/cmd/git.py`)

### Changed

- **Front matter parsing fails loudly instead of silently guessing.** `|`/`>` block
  scalars are joined instead of dropped, and a duplicate key, stray indented line,
  missing colon or unterminated block is returned by `store.frontmatter_problems()`:
  `load_tasks()` skips such a file with a warning and `ai doctor` names it.
  (`lib/tasks/store.py`, `lib/runtime/health.py`)

- **Persisted checks carry provenance.** `ai setup --check NAME=CMD` records
  `addedBy` / `addedAt` on the entry (`ai setup --agent <n>` names the recorder);
  `ai capabilities` publishes the task states, roles and commit types, and
  `branch_types` / `merge_strategy`, so the vocabularies have one machine-readable
  source instead of four prose spellings. Host identity is normalized
  (lower-case short name; `AI_HOST` overrides it).
  (`lib/config/preferences.py`, `lib/cmd/setup.py`, `lib/cmd/capabilities.py`,
  `lib/core/paths.py`)

- **No fabricated `argparse.Namespace` objects in the work path.** `ai task claim`
  and `ai start` call `start_branch(...)` / `claim_task(...)` with explicit
  parameters, and Gitflow setup moved to `lib/git/setup.py` with `setup_git(...)`
  (flow.py keeps the CLI wrapper). A renamed flag is now a real error, not a silent
  one. The `ai start` demo task is marked `demo: true`, and `ai task done` records
  `reviewed_at`.
  (`lib/git/setup.py`, `lib/git/flow.py`, `lib/cmd/task.py`, `lib/cmd/start.py`)

- **Documentation matches the CLI.** One canonical task front-matter table
  (`docs/conventions.md`), one commit-type list, a hotfix note about the automatic
  `feature/` branch, single-line recovery examples (PowerShell-safe), acceptance
  criteria that must name their proof in both templates, adapters that advertise
  only what they ship, and `CHANGELOG.md` is now inside the documented-command test
  (stale paths in history remain exempt).

### Added

- `lib/tests/run.py --coverage` (needs `pip install coverage`), and unit tests for
  scope matching, lease-resource normalization and front-matter parsing.

## [0.9.4] - 2026-11-02

### Fixed

- **Corrupt state files no longer traceback.** Since `read_json` started raising
  `CorruptStateError`, several readers still assumed `None`: a damaged handoff
  marker killed `ai context`/`ai now`, a damaged `runtime/artifacts/MANIFEST.json`
  killed `ai status`, a damaged `task-counter.json` killed `ai task new`, and a
  damaged claim lease could kill `review`/`done`.
  - Handoff markers and checkpoint sidecars are display state: they are skipped
    with a `WARN` naming the file.
  - `ai status` warns and shows zero artifacts; `ai artifact put|clean` refuses
    (appending would silently drop earlier entries) while `list` still works.
  - The task counter is rebuilt from the task files under the `tasks.index`
    lock and a `state_repaired` event is recorded.
  - `claim_started()` treats a damaged lease as "no start time" and releasing
    the git index guard keeps a lease it cannot prove it owns.
    (`lib/runtime/checkpoints.py`, `lib/cmd/status.py`, `lib/cmd/artifact.py`,
    `lib/tasks/lifecycle.py`, `lib/tasks/gates.py`, `lib/git/repo.py`)

- **`ai doctor` now names damaged state instead of leaving it for a crash.**
  It parses every JSON/lease file under `runtime/state/` and `runtime/locks/`
  plus the task counter and artifact manifest: a corrupt lock is an error (with
  the `--force` release hint), the rest are warnings. It also reports leftover
  `.tmp-*.part` files from writes killed mid-rename.
  `ai doctor --fix` removes temp files older than five minutes (a live writer's
  temp file is untouched) and deletes a corrupt `task-counter.json`, which the
  allocator then rebuilds.
  (`lib/runtime/health.py`, `lib/cmd/doctor.py`)

- **A long project check can no longer outlive the git index guard.**
  `ai git finish` acquired `@git/index` with a fixed 600 s TTL and then ran
  `ai check --strict --task`, whose configured timeouts can total far more; the
  lease went stale mid-check and another agent could interleave a commit between
  the check and the merge. The guard's TTL is now the sum of the configured
  check timeouts, and after the check the command re-asserts the lease and
  refuses to merge if it is no longer held.
  (`lib/git/flow.py`, `lib/git/repo.py`, `lib/runtime/leases.py`)

- **Worktree briefing printed a Windows path inside a Markdown code span.**
  The workspace root now uses forward slashes.
  (`lib/git/worktrees.py`)

- **`ai lock acquire` hid validation errors behind "held by None".** A refused
  acquisition with no holder (path traversal, absolute path, oversized TTL) now
  prints the actual reason and skips the misleading `lock_refused` event.
  (`lib/cmd/lock.py`)

- **A title containing `|` or a newline corrupted `tasks/BOARD.md`.** Board
  rendering escapes table cells and flattens newlines in list lines.
  (`lib/tasks/board.py`)

- **`commit_task_metadata` swallowed every git failure.** A failed `git add` or
  `git commit` of task metadata now warns on stderr and records a
  `git_metadata_failed` event instead of silently dropping the ledger commit.
  (`lib/git/repo.py`)

- **The fallback directory mutex spun forever on a stale non-empty directory.**
  When the stale mutex directory cannot be removed (foreign file inside), the
  wait loop now honors its timeout instead of looping past it.
  (`lib/runtime/mutex.py`)

### Changed

- `ai now` prints the unanswered setup questions and the ready-to-run
  `ai setup --set ...` line inline on an unconfirmed project, so a chief sees the
  interview without a second command.
  (`lib/runtime/overview.py`)

- `AGENTS.md`'s fallback pointer now names the real section
  (`tasks/README.md`, "Manual operation"), and the command block lists the
  `ai task new` scope/lock flags plus `git start --carry` and `git commit --verify`.
  (`AGENTS.md`)

### Added

- `lib/tests/test_regressions.py` covers counter rebuild + `state_repaired`,
  a corrupt handoff during `ai context`, a corrupt manifest during `ai status`
  and `ai doctor`, stale-versus-live temp-file sweeping, the check-timeout
  budget that sizes the git index guard, forced takeover of a live lease
  (with its `lock_forced` trail), inline setup questions in `ai now`, the
  refused-overwrite guard in `ai task done`, and the reported failure of a
  task-metadata commit.

## [0.9.3] - 2026-11-02

### Fixed

- **Missing `workspace_state_guard` import broke `ai task new`.** `lib/tasks/lifecycle.py`
  used `workspace_state_guard()` but never imported it, causing a `NameError` on every
  task creation. `create_task()` now also wraps `allocate_task_number()` inside
  `task_index_guard()` so the `tasks.index` lock is held for ID allocation.
  (`lib/tasks/lifecycle.py`)

- **Non-reentrant `registry_mutex()` crashed nested state writes.** `registry_mutex()`
  now tracks whether the current thread already holds the lock and skips the OS advisory
  lock for nested calls (e.g. `workspace_state_guard()` → `acquire_lock()` →
  `registry_mutex()`). Fixes `TimeoutError: lock registry is busy` on Windows where
  `msvcrt.locking` is not re-entrant across file descriptors.
  (`lib/runtime/mutex.py`)

- **Task writes in `git commit` and `git finish` bypassed the state guard.** Both
  `cmd_git_commit()` and `cmd_git_finish()` in `lib/git/flow.py` now wrap
  `store.write_task()` + `board.write_board()` in `workspace_state_guard()`, so a reset
  cannot delete a task file mid-write and the writer cannot resurrect it.
  (`lib/git/flow.py`)

- **No PID liveness for crashed task holders.** `lock_is_stale()` now adds a secondary
  PID+host liveness probe for `task-*` locks only: if the holder is on this host, its PID
  is no longer running, and the lock is older than 30 s, it is treated as stale even if
  TTL has not expired. TTL remains the primary cross-host signal; infrastructure locks
  (`git.index`, `project`, `tasks.index`) are unaffected.
  (`lib/runtime/leases.py`)

- **`--force` on a stale live lease was recorded as `lock_replaced_stale`.** `acquire_lock()`
  now checks `--force` before staleness, so an explicit `--force` always leaves a
  `lock_forced` audit trail.
  (`lib/runtime/leases.py`)

- **Corrupt task lock crashed `ai task done`.** `cmd_task_done()` now catches
  `CorruptStateError` when reading the task lock and treats it as held instead of
  crashing.
  (`lib/cmd/task.py`)

- **Hand-edited or corrupt task files created phantom tasks.** `store.parse_task()` output
  is validated by a new `validate_task_meta()` (requires `id`, `title`, `status`), and
  `load_tasks()` skips invalid files with a `WARN` to stderr instead of letting id-less
  tasks flow through id-keyed logic.
  (`lib/tasks/store.py`)

### Added

- `lib/tests/test_regressions.py` now covers the re-entrant mutex, PID liveness probe,
  force-before-stale ordering, corrupt-lock handling in `done`, and invalid task meta
  validation.

## [0.9.2] - 2026-11-02

### Fixed

- **UnboundLocalError in task discard.** `ai task discard` no longer crashes with
  `UnboundLocalError: local variable 'lock_path' referenced before assignment` when
  the claim lock is missing or corrupt. The function now uses a distinct local variable
  and handles `CorruptStateError` gracefully.
  (`lib/tasks/discard.py`)

- **`lock_is_stale` TypeError on naive timestamps.** The function now safely handles
  offset-naive timestamps by normalizing them to UTC within the try block, preventing
  `TypeError: can't subtract offset-naive and offset-aware datetimes` from poisoning
  `list_locks` consumers (lock status, board, recover, clean).
  (`lib/runtime/leases.py`)

- **`read_json` distinguishes corrupt from missing.** Corrupt state files now raise
  `CorruptStateError` instead of silently returning `None`, preventing corrupt lock
  files from being read as "free" in conflict scans. The function now only catches
  `FileNotFoundError` for the default return value.
  (`lib/core/fsio.py`)

- **Corrupt lock files fail closed in conflict scan.** `resources_overlap()` now
  returns `True` (conflicting) if either resource is `None` (corrupt), preventing
  corrupt lock files from being silently ignored during lock acquisition.
  (`lib/runtime/leases.py`)

- **Audit trail never empty on event write failure.** `append_event()` now writes a
  minimal fallback record (`_fallback: True`, `_error: <error details>`) on final
  failure so the audit trail is never completely empty, preserving investigation
  capability even under extreme contention.
  (`lib/runtime/events.py`)

- **`normalize_id` rejects digit-collapsing ids.** The regex is tightened to
  `[0-9]{1,9}` and a 4-digit limit prevents collisions such as "12" and "012"
  both normalizing to "0012". Non-numeric ids like "T-12a" are also rejected.
  (`lib/core/fsio.py`)

### Added

- **`CorruptStateError` raised from `read_json`.** Callers that guard shared state
  should use `read_json_checked` which fails closed instead of silently treating
  a damaged lock as "free".
  (`lib/core/fsio.py`)

- `lib/tests/test_regressions.py`: coverage for corrupt-lock fail-closed,
  forced-takeover trails, stale-lease replacement, path-traversal refusals,
  naive timestamps, legacy mutex recovery, strict task ids, atomic archiving and
  checked JSON reads.

### Fixed

- **The registry mutex no longer guesses by directory age.** It is now an OS
  advisory lock (released automatically when a process dies); the directory
  mutex remains only as a fallback, and a stale non-empty directory no longer
  spins forever (it times out, and an empty leftover is upgraded).
- **Corrupt locks fail closed.** A damaged lease file is a conflict instead of
  reading as "free"; `--force` removes it and records `lock_forced`. A stale
  lease on the same resource is replaced as `lock_replaced_stale`, and a forced
  takeover of a live same-resource lease is recorded instead of being ignored.
  Lock files are created with `fsync` and verified before use.
- `ai lock acquire` reports validation errors (repo-relative paths, absolute
  paths, `..`, oversized TTL) instead of claiming the resource is "held by None".
- Strict task ids: `normalize_id` rejects non-numeric and traversal values, and
  `task show|claim|done` return a clean "No task with id" instead of crashing.
  Leading zeros no longer allow ids longer than nine significant digits.
- State writes `fsync` before the atomic rename, retry Windows sharing
  violations, and `read_json_checked` distinguishes a missing file from a
  corrupt one. Naive (offset-free) timestamps are read as UTC, so
  `ai lock status` and heartbeat no longer fail with `TypeError`.
- `ai task discard` no longer crashes when the claim lock or linked spec id is
  missing/invalid; `ai task done` refuses to overwrite an existing archived task
  file and keeps the active task in place.
- `ai task block/unblock` check ownership before writing and restore
  `blocked_from` (`review`/`changes_requested`) instead of dropping it.
- Git layer: commands time out after 300 s, Windows runs hide console windows,
  porcelain output is parsed with `-z` (spaces in names), a failed merge aborts
  cleanly, `git.merge` (`ff`/`no-ff`) is honored, and the index guard release is
  serialized.
- `ai doctor`: an unknown `--task` fails, `--agent` without a task warns that no
  evidence can be attached, and check runs record their duration/timeout.
- Configuration errors surface as one actionable `ConfigError` message instead of
  a traceback; `ai.cmd` verifies Python 3 and returns an honest exit code.
- Documentation: the chief loop now uses `ai plan apply ... --role chief`, the
  spec step precedes the claim, `--force` is documented as an operator-only
  escape hatch, per-task evidence (`ai check --task --agent`) and the lease step
  before committing are explicit, `changes_requested` appears in the state
  diagrams, and the canonical task front matter is defined once.

## [0.9.0] - 2026-11-01

### Added

- **Chief-only task creation.** `ai task new` and `ai plan apply` refuse unless the
  caller declares `--role chief` (or `AI_ROLE=chief`) **and** the user's setup
  answers are stored (`workflow.chiefOnlyTasks`, default on). `ai start` no longer
  sets Git up before the user chose, and its next step on an empty project is
  `ai setup` / `ai plan apply`, never `ai task new`. The pointer files written by
  `ai adopt` and `AGENTS.md` now start with "who are you?".
- **"No spec, no code" is enforced.** A task cannot be claimed while its spec is
  still the template (`workflow.requireSpec`, default on; `--no-spec` tasks are
  exempt). `ai plan apply` writes each task's intent and acceptance criteria into
  its spec. `ai doctor` warns about done tasks whose spec stayed in `specs/active/`.
- `ai git setup --yes`: confirms the baseline commit without a terminal (lists the
  files, refuses secret-looking ones such as `.env`, `*.pem`, `id_rsa`).
  `ai git start --carry` starts the branch with uncommitted product files; the
  refusal message now says so.
- `ai task new --lock GLOB`; a task's `--allow` paths are locked when it is claimed.
  A manual `ai lock acquire` inside the agent's own broader lock for the same task
  is accepted as covered instead of refused.
- README rewritten: copy-paste install for macOS/Linux, Windows PowerShell and
  Windows cmd, ready-made prompts for the chief, implementers and reviewers.
- Smoke tests for commands that had none (`block`/`unblock`, `link`, `discard`,
  `brief`, `artifact`, `clean`, `git begin`/`end`, ADR numbering).
- Documentation tests (`lib/tests/test_docs.py`): every `ai ...` command written in
  a guide must exist in the parser, stale paths fail the build, `capabilities`
  must list every command, the version must match the changelog, and `lib/` may
  not contain unused imports.

### Changed

- **Delivery hands the task over.** `ai task review` runs the project checks when
  required, records the evidence, frees every lock of the task and clears the
  owner, so a reviewer can take it at once. The separate `ai task release` step is
  gone from the flow (`release` after delivery is a harmless no-op).
- A reviewer sees the same queue `ai now` shows: only delivered, unowned tasks.
- Without Git (`git.enabled=false`) the reviewer is told `ai task done`, never
  `ai git finish`; `ai start` respects the same switch and claims through the same
  one-command path as `ai task claim` (file locks, branch).
- `ai now` right after a claim says "read the spec and do the work" instead of
  suggesting `ai check`; evidence lines read `unit passed` (not `unit=0`, which
  looked like a test count); `ai setup --set ...` confirms in one line.
- `ai task review` and `done` free **every** lock tagged with the task, also the
  hand-taken ones; `done` moves the spec to `specs/done/` and updates the task.
- `ai now --json` and `ai context --json` return compact task records (no bodies).
  `ai check --json` adds `results`, `task` and the evidence state; `ai check`,
  `ai task next` and `ai git finish` keep stdout a single JSON document in
  `--json` mode (check output and claim chatter go to stderr).
- `ai artifact put` no longer crashes on a path from another Windows drive;
  `ai clean` without flags says what to pass instead of "Cleaned 0 item(s)";
  concurrent `ai decision new` calls get distinct numbers.
- `docs/`, GUIDE, `tasks/README.md`, conventions and the roadmap were brought in
  line with the CLI (command surface, branch names, review flow).

### Fixed

- Rework after `request-changes` could never re-enter review in strict mode:
  returning the task now invalidates earlier evidence and the next `ai task review`
  re-runs the checks.
- Lock file names collided for resources differing only in `/` versus `-`
  (`src/a`, `src-a`): the file name now carries a digest of the resource, and
  `release`/`heartbeat` verify the resource, so one lock can no longer free another.
- A producer could merge its own work with `ai git finish`; it is now refused
  (`--force` overrides, as for `done`).
- `tasks/TEMPLATE.md` front matter no longer carries inline `# comments` that the
  parser read as values.
- `ai check` records its per-task evidence only; the unread `last-check.json` and
  its code are removed.

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
- Forced lock takeovers are recorded as `lock_forced` events; forced `done`
  records `forced` and `submitted_by` in the event log and the task history.

### Changed

- Required verification with no configured project checks is now a hard error at
  review (not a free pass). `git.enabled=false` turns the Git steps off.
- `config/` and `docs/decisions/` no longer count as product changes when
  starting a task branch; `ai git finish` ignores ledger changes (tasks, specs,
  config) when checking that the main tree is clean.
- Checkpoint age and `now --json` (`schema: 1`) read their values from config /
  carry a schema version.

### Fixed

- A reviewer claiming a task in `review` no longer flips it back to `in_progress`.

## [0.7.0] - 2026-10-30

### Changed

- **Restructure.** The 4,800-line `scripts/ai.py` is split into `lib/`, which
  holds scripts only: `lib/{core,config,runtime,tasks,specs,git,decisions,cmd,tests}`.
  `ai.py` is now a thin entry point at the workspace root (launchers `ai` and
  `ai.cmd` moved with it). Data stays where it was: `tasks/`, `specs/`,
  `runtime/`, `config/`, `templates/git/`, `docs/decisions/`. See `lib/README.md`.
  Command behavior is unchanged.
- Commands are auto-discovered from `lib/cmd/*.py` (and `skills/*/skill.py`);
  adding a command is one file.
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
  requires a green full `ai check`. Configure with `workflow.requireReview` and
  `workflow.requireCheck` in `config/workspace.json`. `--force` bypasses and is
  logged.

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
