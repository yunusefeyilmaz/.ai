# AGENTS.md — read this first

`.ai` is the workspace: the `ai` binary is the entry point (built from `src/`;
launchers `ai` and `ai.cmd`), state lives in
`tasks/`, `specs/`, `runtime/`, `config/`. AI output stays under `.ai/`; the rest is
product territory.

## Who are you?
- No tasks yet and the user gave you a job -> **chief**: run `ai now --role chief`, ask
  the setup questions (review? Git? tests? checks? workers?), store them, then plan.
  Do not code and do not create tasks as a worker.
- "Implementer" -> `ai task next` claims one; "reviewer" -> `ai task next --review`;
  `.ai` is a dot-folder, so use the `ai` commands, not file globs, to read state.

## Session loop
```sh
ai now --agent <n> [--role chief|implementer|reviewer]   # state + the ONE next command
ai context                                               # only when new: open work, ADRs
```
Run the command after `NEXT`, then `ai now` again; read task/spec files only when asked.

- **chief**: `ai now --role chief` -> `ai setup` (ask review/checks/git/tests/workers/mode/playbook) -> `ai blueprint propose` (facts) -> `ai blueprint propose --from analysis.json` (the AI's design) -> the user approves or changes it (`ai blueprint approve` / `ai blueprint revise --set path.to.key=value`) -> `ai plan apply plan.json --role chief` -> fill specs -> `ai status`.
- **implementer**: `ai task next` (claim + locks + branch) -> work -> `ai task review`, then stop.
- **reviewer**: `ai task next --review` -> `ai git finish` + `ai task done`, or `ai task request-changes`.
- **solo playbook**: one agent designs, implements and reviews; `ai task done` accepts the same agent only when `workflow.playbook` is `solo`.

## Required order (enforced)
1. **Spec first.** Edit the linked file in `specs/active/` before any claim.
2. `ai task next --agent <n>` needs a filled spec; it takes the task's file locks
   and opens its branch. It refuses a missing dependency or a live lock.
3. `ai git setup` once per clone; the claim opens the branch.
4. Work inside your locks; extra files: `ai lock acquire <path> --agent <n> --task
   <id>`. Checkpoint at milestones: `ai checkpoint <id> --agent <n> --next "<step>"`.
5. `ai git verify --strict`, then `ai git commit --task <id> --agent <n> --type feat
   --message "<subject>"`; every staged path needs your lock. Then `ai check --task
   <id> --agent <n>` runs the project's `checks`; red means stop.
6. `ai task review <id> --agent <n>` runs the checks and hands over; a different agent
   runs `ai git finish` + `ai task done`, or `ai task request-changes`.

The producer never approves its own work; `ai task done` never works straight from
`in_progress`, and it refuses a task whose branch is not merged into the integration
branch (`ai task reopen <id>` puts a wrongly-archived task back in review). `--force` is the human's escape hatch, only on explicit request.

## Locks
A lease is JSON under `runtime/locks/`; a live one is a refusal. Staleness comes only
from `updated_at` and `locks.staleAfterSeconds` (default 3600) in
`config/workspace.json`; the PID is diagnostic, not a liveness test, because a claim
must outlive the CLI that created it. Refresh with `ai lock heartbeat`; never delete a
lock file.

## Workers and continuation
If `ai task claim|next` prints `worktree: <path>`, that directory is **your** checkout:
`cd` there and edit only there; a worktree may contain a copy of the ledger, but the
CLI resolves it back to the main workspace. Run the shared CLI by the absolute path
it printed. `ai git commit`, `ai check --task` and `ai task review` find your
worktree themselves and run checks there; never edit the main checkout. At ~70%
context stop opening work; at ~85% `ai checkpoint`; before the window closes run
`ai handoff` and stop.

## Playbooks, modes and tokens
`workflow.playbook` decides who may approve: `solo` (one agent designs, implements,
reviews), `pair` (producer + separate reviewer) or `team` (chief, workers, reviewers).
`mode` (`lite`/`strict`) decides how much process runs. The user picks both with
`ai setup`; the chief must not pick for them.

Spend tokens on work, not on rediscovery:
- read `ai now` and run its ONE `NEXT` command; read task/spec files only when asked;
- `ai brief --max-chars N` is the paste-ready extern model brief; the approved
  `config/blueprint.json` carries naming/architecture/checks;
- `ai review <id> --stat` before opening a full diff;
- never re-read the whole repository or all docs for context that `ai now`,
  `ai brief` or the task already provides.

## Invariants
1. Nothing AI-generated escapes `.ai/`; claim before you work, one task per session.
2. Lock shared resources; a live lock is a refusal; never delete lock files.
3. No spec, no code; behavior changes need testable acceptance criteria.
4. The producer never verifies its own work; "done" means `ai check` is green.
5. Record lasting decisions with `ai decision new "<title>"`.
6. Respect `mode` (`lite` or `strict`); Gitflow for every file-changing task, and
   destructive actions (`ai task discard`, `ai reset --hard`) only on request.

## Command surface
```sh
ai now|context|brief|start|setup|doctor|check|status|metrics|capabilities|version
ai plan apply|example   ai task new|list|show|ready|next|claim|release|review|request-changes|done|reopen|block|unblock|link|discard
ai lock acquire|release|heartbeat|status   ai checkpoint|handoff|resume|recover
ai git setup|start|commit|verify|finish|begin|end   ai history   ai decision new|list
ai artifact put|list|clean   ai review <id>   ai clean   ai reset
```

`ai capabilities --json` is the machine-readable surface; the parser wins. If `ai` is
unavailable, follow the same protocol by editing files directly (see
`tasks/README.md`, "Manual operation").
