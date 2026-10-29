# Scripts

The `ai` command is the fast path. The protocol in `docs/` is the contract and
works without any runtime; the CLI only automates it.

## Launchers

- `scripts/ai` — POSIX launcher (Linux, macOS, Git Bash). Finds `python3`, `python`, or `py`.
- `scripts/ai.cmd` — Windows launcher. Finds `py -3` or `python`.
- `scripts/ai.py` — the engine (stdlib only, Python 3.8+).

No installation step is required when Python 3 is already on the machine. If it
is not, agents can still follow the Markdown protocol by hand.

On Unix, if Git did not preserve the executable bit, run `chmod +x scripts/ai`
once, or invoke it as `sh scripts/ai ...`. Windows users always use `ai.cmd`.

## Commands

| Command | Purpose |
|---------|---------|
| `ai init [--wire]` | Create runtime directories; `--wire` also writes the root adapters. |
| `ai start [--agent <name>] [--demo\|--no-demo] [--json]` | First run: prepare, detect Git, create one task with a spec, optionally claim it. |
| `ai adopt [--check] [--print] [--ci] [--force]` | Wire the workspace into root AI tool configs. |
| `ai doctor [--strict] [--json]` | Workspace health: structure, config, tasks, locks, adapters. |
| `ai check [--fast] [--strict] [--json] [--no-commands]` | The single verification contract. |
| `ai status [--json]` | Tasks, locks, checkpoints, handoffs, quarantined artifacts. |
| `ai capabilities` | Machine-readable CLI contract (commands, state, exit codes). |
| `ai task new "<title>" [--priority high] [--spec <path>] [--no-spec] [--depends-on 0002]` | Create a task with a race-safe id and a spec skeleton. |
| `ai task list [--all] [--json]` | List tasks and refresh `tasks/BOARD.md`. |
| `ai task show <id> [--json]` | Print one task. |
| `ai task ready [--json]` | List claimable tasks (todo, dependencies done, no live lease). |
| `ai task next --agent <name> [--json]` | Atomically claim the highest-priority ready task. |
| `ai task claim <id> --agent <name> [--force]` | Atomically lock and own a task. |
| `ai task release <id> --agent <name> [--force]` | Give the task back. |
| `ai task block <id> --agent <name> --reason "..."` | Mark a task blocked. |
| `ai task unblock <id> --agent <name>` | Return a blocked task to `todo`. |
| `ai task done <id> --agent <name> [--force]` | Mark done, archive to `tasks/done/`, release the lock. |
| `ai lock acquire <resource> --agent <name> [--task <id>] [--ttl s] [--force]` | Lock a path, glob or subsystem. |
| `ai lock release <resource> --agent <name> [--force]` | Release a lock. |
| `ai lock heartbeat <resource> --agent <name>` | Extend a long-running lock. |
| `ai lock status [--json]` | Show locks and stale state. |
| `ai checkpoint [id] --agent <name> [flags]` | Save resumable context; merges with the previous checkpoint. |
| `ai handoff [id] --agent <name> --reason "..."` | Checkpoint, write a handoff marker, print the next prompt. |
| `ai resume [id] [--json]` | Print the saved context, drift report and resume prompt. |
| `ai brief [id] [--max-chars N] [--json]` | Paste-ready brief for a chat AI without repository access. |
| `ai recover [--apply] [--json]` | Detect or repair inconsistent task/lock state. |
| `ai git begin --agent <name> --task <id>` | Take the shared `@git/index` lock. |
| `ai git end --agent <name>` | Release `@git/index`. |
| `ai git verify [--strict] [--json]` | Staged paths must be covered by a held lock. |
| `ai artifact put <path> [--reason ...]` | Move stray AI scratch files into `runtime/artifacts/`. |
| `ai artifact list [--json]` / `ai artifact clean --all` | Inspect or purge quarantined files. |
| `ai clean [--stale-locks] [--logs]` | Housekeeping. |

## Lock semantics

- Resources are repo-relative. Absolute paths are rejected.
- Paths and globs overlap (`src/billing` conflicts with `src/billing/x.py`).
- Locks are advisory leases with a TTL; a live lock is a refusal.
- `--force` ignores a live holder. Use it only after checking `ai lock status`.
- `@git/index` and `tasks.index` are reserved global resources.

## Exit codes

- `0` — success / all checks passed.
- `1` — a check failed or a lock/claim was refused.
- `127` — no Python 3 found (use the manual protocol).
