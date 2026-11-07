# Porting notes: Python `.ai` -> Rust

This checkout is a Rust port of the Python workspace in `../.ai`. It keeps the
same on-disk contract, so both implementations can operate on one workspace:

- task files: YAML-ish front matter written by `tasks/frontmatter.rs` / `tasks/store.rs`
- specs: `specs/active`, `specs/done`, acceptance-criteria parser shared by the
  gate, `ai doctor`, `ai spec` and `ai review`
- locks: `runtime/locks/*.lock` JSON leases
- events: `runtime/state/events.jsonl` plus date-rotated archives
- checkpoints/handoffs: `runtime/state/checkpoints`, `runtime/state/handoff`
- board: `tasks/BOARD.md`
- decisions: `docs/decisions/NNNN-slug.md`

## Source layout

`src/` mirrors the Python `lib/` package tree:

```
src/
  main.rs              CLI parser + dispatch (ai.py)
  core/                error, fsio, time, workspace(paths)
  config/              settings, preferences, roles, adopt
  tasks/               frontmatter, store, lifecycle, history, board, plan, scope, gates
  specs/               spec
  runtime/             checkpoints, dirs, events, evidence, health, leases,
                       metrics, mutex, overview
  git/                 repo, flow (Gitflow + setup), worktrees
  decisions/           adr
  ui/                  dashboard
  cmd/                 one module per CLI command:
                       adopt artifact brief capabilities checkpoint clean
                       context decision doctor git history init lock metrics
                       now plan recover reset review setup spec start status
                       task ui version worktree (+ common)
```

| Python | Rust |
| --- | --- |
| `ai.py` | `src/main.rs` |
| `lib/core/paths.py` | `src/core/workspace.rs` |
| `lib/core/fsio.py` | `src/core/fsio.rs` |
| `lib/core/timeutil.py` | `src/core/time.rs` |
| `lib/config/settings.py` | `src/config/settings.rs` |
| `lib/config/preferences.py` | `src/config/preferences.rs` |
| `lib/config/roles.py` | `src/config/roles.rs` |
| `lib/config/adopt.py` | `src/config/adopt.rs` |
| `lib/tasks/store.py` | `src/tasks/store.rs`, `src/tasks/frontmatter.rs` |
| `lib/tasks/lifecycle.py` | `src/tasks/lifecycle.rs` |
| `lib/tasks/history.py` | `src/tasks/history.rs` |
| `lib/tasks/board.py` | `src/tasks/board.rs` |
| `lib/tasks/plan.py` | `src/tasks/plan.rs` |
| `lib/tasks/scope.py` | `src/tasks/scope.rs` |
| `lib/tasks/gates.py` | `src/tasks/gates.rs` |
| `lib/specs/spec.py` | `src/specs/spec.rs` |
| `lib/runtime/leases.py` | `src/runtime/leases.rs` |
| `lib/runtime/checkpoints.py` | `src/runtime/checkpoints.rs` |
| `lib/runtime/evidence.py` | `src/runtime/evidence.rs` |
| `lib/runtime/dirs.py` | `src/runtime/dirs.rs` |
| `lib/runtime/events.py` | `src/runtime/events.rs` |
| `lib/runtime/health.py` | `src/runtime/health.rs` |
| `lib/runtime/metrics.py` | `src/runtime/metrics.rs` |
| `lib/runtime/mutex.py` | `src/runtime/mutex.rs` |
| `lib/runtime/overview.py` | `src/runtime/overview.rs` |
| `lib/git/repo.py` | `src/git/repo.rs` |
| `lib/git/flow.py` | `src/git/flow.rs` |
| `lib/git/setup.py` | `src/git/flow.rs` (`setup`) |
| `lib/git/worktrees.py` | `src/git/worktrees.rs` |
| `lib/decisions/adr.py` | `src/decisions/adr.rs` |
| `lib/ui/*` | `src/ui/dashboard.rs` (static frame only) |
| `lib/cmd/*.py` | `src/cmd/*.rs` |

## Build and run

```sh
cargo build --release
./target/release/ai doctor        # or ai.cmd on Windows
```

Run the suite with `cargo test` (183 tests: unit + end-to-end). Each integration
test builds a throwaway workspace under the OS temp directory; nothing touches
this checkout.

`ai.cmd` (Windows) and `ai` (POSIX) are thin launchers: release binary, debug
binary, then `cargo run`. On macOS/Linux mark the shell launcher executable once:
`chmod +x ai`.

## Tests

`cargo test` runs 183 tests: unit tests in the library plus one integration
file per Python suite that was ported. `tests/support/mod.rs` is the port of
`lib/tests/_workspace.py`: every test gets a private, normalised workspace
copied from this checkout (no tasks, empty checks, preferences unset).

| Python suite | Rust file |
| --- | --- |
| `test_acceptance_criteria.py` | `tests/spec_criteria.rs` |
| `test_board.py` | `tests/board.rs` |
| `test_lock_ownership.py` | `tests/locks.rs` |
| `test_workflow.py` | `tests/task_flow.rs` |
| `test_request_changes.py` | `tests/task_flow.rs` |
| `test_frontmatter_lists.py` | `tests/frontmatter.rs` |
| `test_task_ids.py` | `tests/task_ids.rs` |
| `test_check_gate.py` | `tests/check_gate.rs` |
| `test_now_json.py` | `tests/now_setup.rs` |
| `test_setup_gate.py` | `tests/now_setup.rs` |
| `test_review_gate.py` | `tests/review_gate.rs` |
| `test_checkpoint_gate.py` | `tests/checkpoint_gate.rs` |
| `test_claim_rollback.py` | `tests/claim_rollback.rs` |
| `test_done_stale_lock.py` | `tests/done_stale_lock.rs` |
| `test_worktree.py` | `tests/worktree.rs` |
| `test_events_fallback.py`, `test_metrics.py` | `tests/events_metrics.rs` |
| `test_evidence_state.py` | `tests/evidence_state.rs` |
| `test_metadata_commit.py` | `tests/metadata_commit.rs` |
| `test_doctor.py` | `tests/doctor.rs` |
| `test_commands_smoke.py` | `tests/commands_smoke.rs` |
| `test_adopt_ignore.py` | `tests/adopt_ignore.rs` |
| `test_capabilities.py` | `tests/capabilities.rs` |
| `test_platform.py`, `test_launchers.py` | `tests/platform.rs` |
| `test_docs.py` | `tests/docs.rs` |
| — (general smoke) | `tests/cli.rs` |

Not ported yet, because they exercise Python-only machinery or need a TTY:
`test_reset_mutex.py` (drives the interactive reset in-process and probes the
mutex from Python), `test_ui.py` (the animated TUI), `test_protocol.py`,
`test_field_report.py`, `test_regressions.py`, `test_reliability.py`,
`test_e2e_flow.py`, `test_start.py`/`test_onboarding.py`,
`test_chief.py`, `test_doctor_semantics.py`, `test_adapter_contract.py`,
`test_review_package.py`. Their behaviour that this port implements is covered
indirectly by the suites above; the rest is listed here so the gap is visible
instead of implied.

## Platform support

The binary is plain portable Rust (no OS-specific crates, no FFI) and is
intended to run on Windows, macOS and Linux:

- Paths are built with `PathBuf`; user-facing relative paths always use `/`.
  `MAIN_SEPARATOR` is used only when joining a stored `/` path onto disk.
- Project checks run through `cmd /C` on Windows and `sh -c` elsewhere.
- File replacement (`write_text_atomic`) retries and falls back to copy+remove,
  which covers Windows rename-over-existing and cross-device moves.
- Advisory locks use `fs2`, which maps to `LockFileEx` on Windows and `flock`
  on Unix.
- Symlinks are removed with `remove_dir` on Windows and `remove_file` on Unix.
- Git is required only for Gitflow commands; everything else works without it.
- `.gitattributes` pins `*.cmd` to CRLF and everything else (including the
  POSIX `ai` launcher) to LF.
- `rust-version = "1.85"` in `Cargo.toml` is verified by CI (the dependency set
  in `Cargo.lock` needs an edition-2024-capable Cargo).

## CI jobs (`.github/workflows/ci.yml`)

| Job | What it proves |
| --- | --- |
| `test` (ubuntu, macos, windows) | `cargo build/test --locked --all-targets`, then `init`, `doctor`, `capabilities`, `version`, and both launchers (`./ai`, `ai.cmd`) |
| `lint` | `cargo fmt --all --check` and `cargo clippy --all-targets -- -D warnings` |
| `msrv` | the declared 1.85 toolchain still compiles the locked dependency set |
| `release` | release binaries packaged per OS, uploaded only after `test` + `lint` pass |

Runs are serialized per ref (a new push cancels the previous run) and need only
`contents: read`.


Known caveat: `ai ui` prints a single static frame everywhere; the animated
Python TUI is not ported.

## Status

Version **1.1.0** is the first release of the Rust port.

- Full CLI surface is implemented: now/context/brief/start/init/setup/doctor/
  check/status/metrics/capabilities/version/plan/task/lock/checkpoint/handoff/
  resume/git/history/decision/spec/artifact/clean/review/reset/recover/adopt/
  worktree/ui.
- `cargo test` runs 183 tests (10 unit + 173 end-to-end) across 23 integration
  files; see the matrix above.
- `ai ui` is a static read-only frame; the animated Python TUI (`lib/ui/`) is
  not ported.
- The Python-only `python 3 not found` exit code (127) is not applicable; the
  Rust binary uses `0`/`1`, `2` for an invalid `--since`, and `127` only when
  `git` itself is missing.
- `ai reset --hard` and `ai task discard` still require an interactive terminal,
  matching the Python safety rules.
