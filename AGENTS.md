# AGENTS.md — read this first

This project uses the `.ai` workspace. `ai.py` is the single entry point; the
the scripts it runs are in `lib/`; the state it manages stays in `tasks/`, `specs/`, `runtime/`. Everything AI-generated stays
under `.ai/`. The rest of the repository is product territory.

## Session loop (follow it, do not improvise)

```sh
ai now --agent <n> [--role chief|implementer|reviewer]   # 10 lines: state + the ONE next command
ai context                                               # only when new: open work, shipped work, ADRs
```

The user tells you your role ("you are the chief / an implementer / a reviewer");
pass it as `--role`. Roles and their one-command loops:

| Role | Loop |
|------|------|
| **chief** (`agents/orchestrator.md`) | `ai setup` (ask the user, stored in config) -> `ai plan apply plan.json` -> fill specs -> `ai status` |
| **implementer** | `ai task next` (claims + locks + branch) -> work -> `ai task review` (checks + delivers). **Then stop** and wait for the user |
| **reviewer** | `ai task next --review` -> `ai git finish` + `ai task done`, or `ai task request-changes` |

Run the command printed after `NEXT`, then run `ai now` again. It reads the task
state, Git and the last check, so you never have to work out the order yourself.
Read task and spec files only when `NEXT` or the task asks you to.

## Required order (enforced, not advice)

| # | Step | Command | Refused when |
|---|------|---------|--------------|
| 1 | Pick work | `ai task next --agent <n>`: also takes the task's file locks and opens its branch | a dependency is not done, or a declared file is locked |
| 2 | Spec | edit the linked file in `specs/active/` | — (no spec, no code) |
| 3 | Git base | `ai git setup` (once per clone) | — |
| 4 | Branch | automatic at claim when Git is on; manual: `ai git start --task <id> --agent <n> --type feature` | before editing, always |
| 5 | Work | the task's declared `locks` are already held; extra files: `ai lock acquire <path> --agent <n> --task <id>`; edit, `ai checkpoint <id> --agent <n> --next "<step>"` | a live lock is a refusal |
| 6 | Commit | `ai git verify --strict`, then `ai git commit --task <id> --agent <n> --type feat --message "<subject>"` | staged paths not covered by your locks |
| 7 | Check | `ai check --task <id> --agent <n>` (runs the *project's* `checks` from `config/workspace.json`) | red. Strict mode needs green evidence for this task on the current HEAD before review |
| 8 | **Review** | `ai task review <id> --agent <n>` (runs the project checks itself when required), then `ai task release <id> --agent <n>` | not `in_progress`, not yours, or (strict) no green check |
| 9 | **Merge + done** (a *different* agent) | `ai git finish --task <id> --agent <r>`, then `ai task done <id> --agent <r>` | task not in `review`, or `<r>` is the producer |
| 9b | Not good enough? | `ai task request-changes <id> --agent <r> --reason "..."` | not in `review`, or `<r>` is the producer. The producer reclaims it |

`ai task done` never works straight from `in_progress`. The producer never
approves its own work. `--force` is an operator escape hatch; use it only when
the human says so.

## Parallel workers (worktrees)

If `ai task claim|next` prints `worktree: <path>`, that directory is **your** checkout: `cd` into it and edit
files only there. It has no `.ai/`; run the shared CLI by the absolute path it printed. `ai git commit`,
`ai check --task`, `ai task review` find your worktree on their own. Never edit the main checkout.

## Reading a task

`ai history <id>` shows who moved it, when, why and on which proof; `ai resume <id>` says whether
the recorded verification is still valid. A task may declare `scope_allowed`/`scope_forbidden`:
`ai git verify --task <id>` before committing.

## Running out of tokens (so another AI can continue)

- ~70% of context: stop starting new work. ~85%: `ai checkpoint <id> --agent <n> --next "<step>"`.
- Before the session ends or on a hard limit: `ai handoff <id> --agent <n> --reason "<why>"`.
- The next agent (any vendor): `ai now` shows `HANDOFF`; then `ai resume <id>` prints the
  checkpoint, the drift against the real repo, and a resume prompt. Verify drift before trusting it.
- Checkpoints, handoffs, locks, events and logs are in `runtime/` (never committed).

## Invariants

1. **Nothing AI-generated escapes `.ai/`.** Notes, scratch files, logs go to `ai artifact put` or `runtime/`.
2. **Claim before you work.** One task per session. Never edit a task another agent owns.
3. **Lock shared resources.** A live lock is a refusal, not a suggestion. Never delete lock files.
4. **No spec, no code.** Behavior changes need testable acceptance criteria in `specs/`.
5. **Producer never verifies its own work.** Roles in `config/workspace.json` (`team`) can limit who may review/approve; if `ai` says an action is denied, do not work around it. Review runs in a separate session.
6. **"Done" means `ai check` is green.** Attach the command and result to the task.
7. **Record lasting decisions:** `ai decision new "<title>"` (ADR in `docs/decisions/`).
8. **Respect the mode** in `config/workspace.json`: `lite` or `strict` (human gates at spec, plan, triage).
9. **Gitflow for every file-changing task** unless the user says not to use Git. Dubious-ownership errors: ask the
   user to trust only this exact checkout; never a wildcard `safe.directory`.
10. **Destructive operator actions** (`ai task discard`, `ai reset --hard`) only when the user explicitly directs them.

## Where things live

`lib/` holds only scripts. Data stays in the folders below.

| Need | Data (read/write via `ai`) | Scripts (`lib/`) |
|------|----------------------------|------------------|
| Entry point | `ai.py`, launchers `ai`, `ai.cmd` | — |
| Tasks, board | `tasks/active`, `tasks/done`, `tasks/BOARD.md` | `lib/tasks/` (rules: `gates.py`, `workflow.py`) |
| Specs | `specs/active`, `specs/done` | `lib/specs/` |
| Locks, checkpoints, handoffs, events, artifacts, logs | `runtime/` (never committed) | `lib/runtime/` |
| Git flow, commit/PR templates | `templates/git/` | `lib/git/` |
| Decisions (ADRs) | `docs/decisions/` | `lib/decisions/` |
| Config (`workspace.json`) | `config/` | `lib/config/` |
| CLI commands (one file each) | — | `lib/cmd/` |
| Paths, atomic IO, time | — | `lib/core/` |
| Tests of the workspace tooling itself (not your project; run only if you changed `.ai`) | — | `lib/tests/` |
| Optional extensions (future) | `skills/` | — |
| Module map and call flow | `lib/README.md` | |
| Deep dives: flow, locks, git, recovery | `docs/` | |

## Commands

```sh
ai now [--agent <n>] [--role r] ai context [--limit N]         ai doctor        ai check
ai setup [--set k=v ...]        ai plan apply|example         ai worktree list|path|prune
ai task new|list|show|ready|next|claim|release|review|request-changes|done|block|unblock
ai lock acquire|release|heartbeat|status
ai checkpoint|handoff <id> --agent <n>   ai resume <id>   ai recover [--apply]
ai git setup|start|commit|verify|finish|begin|end
ai history <id> [--evidence]     ai decision new|list            ai artifact put|list|clean     ai status [--board]
```

If `ai` is unavailable, follow the same protocol by editing files directly
(see `docs/task-flow.md`); do not invent a shortcut.
