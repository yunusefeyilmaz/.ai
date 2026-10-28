# AGENTS.md — read this first

You are working in a project that uses the `.ai` engineering workspace. All AI
state lives under `.ai/`. The project outside it is product territory.

## Invariants

1. **Nothing AI-generated escapes `.ai/`.** Tasks, specs, notes, logs, scratch
   files and experiments go under `.ai/`. Product code goes in the project.
2. **Claim before you work.** Find or create a task in `tasks/active/`, then
   `ai task claim <id> --agent <name>`. Never edit a task owned by another agent.
   If the human's request has no task, create the task (or a task set with
   `depends_on`) and write the spec first. Do not start coding from a chat
   request alone.
   When several tasks exist, `ai task ready` lists what can start and
   `ai task next --agent <name>` atomically claims the highest-priority ready
   task. Never bypass `depends_on` with `--force`.
3. **Lock shared resources.** Before editing a file or subsystem another agent
   may touch, `ai lock acquire <resource> --agent <name> --task <id>`. Release
   when done. A live lock is a refusal, not a suggestion.
4. **One task per agent session.** Do not interleave two tasks.
5. **No spec, no code.** Behavior changes get a spec in `specs/` with testable
   acceptance criteria before implementation.
6. **Producer never verifies its own work.** Review runs in a separate session
   or subagent that sees the diff and the spec.
7. **"Done" means `ai check` is green.** Attach the command and its result to
   the task. "It works" is not evidence.
8. **Record lasting decisions** as an ADR in `docs/decisions/`.
9. **Respect the mode.** `config/workspace.json` sets `lite` or `strict`.
   Strict requires human gates at spec, plan and triage.
10. **Checkpoint before the context window fills.** At ~70% stop starting work;
    at ~85% run `ai checkpoint`; before the end run `ai handoff`. A new session
    resumes with `ai resume <id>` and verifies drift before trusting it.
11. **Never bypass a live lock.** Do not delete lock files. Wait for TTL,
    heartbeat if you are the owner, or run `ai recover --apply` for structural
    leftovers.
12. **Do not discard tasks.** `ai task discard` is a permanent, interactive
    operator action; agents may invoke it only when the user explicitly directs
    the discard.
13. **Do not hard reset the workspace.** `ai reset --hard` clears task/spec and
    runtime state; agents may invoke it only when the user explicitly requests
    a reset.
14. **Use Gitflow for every file-changing task unless the user explicitly says
    not to use Git.** Run `ai git setup` once in the clone; it initializes Git,
    creates the base branches, and asks before committing an initial snapshot
    when the repo has no commits. Claim the task, then successfully run
    `ai git start` before editing. Commit with `ai git commit`; a separate
    reviewer merges with `ai git finish` before the task is done. Read-only work
    needs no branch. If Git reports dubious ownership, ask the user to approve
    trusting only this exact checkout; never use a wildcard safe.directory.

## Start of session

1. If resuming, run `ai resume <id>` and read the drift report.
2. Read `docs/task-flow.md`, `docs/multi-agent.md`, `docs/git-workflow.md`, and
   `GUIDE.md`.
3. Run `ai status` (or read `tasks/BOARD.md`).
4. Before file-changing work, run `ai git setup` once in this clone. It runs
   `git init` and creates the production/integration base when missing; its
   initial baseline lists non-ignored project files and requires interactive
   confirmation before committing. If Git reports dubious ownership, request
   approval for this exact checkout before continuing.
5. Claim a task, or create one with `ai task new "<title>"`. For a multi-step
   request, create the task set and dependencies first.
6. After claiming a task and before editing any file, run
   `ai git start --task <id> --agent <name>
   --type <type>`. If it fails, stop before editing and report the blocker.
7. Work, checkpoint at milestones, then stage owned paths, run
   `ai git verify --strict`, and commit with `ai git commit`. Follow the separate
   review and merge flow in `docs/git-workflow.md` before marking the task done.

## Where things live

| Need | Path |
|------|------|
| Rules and invariants | `.ai/AGENTS.md` (this file) |
| Usage guide and prompts | `.ai/GUIDE.md` |
| Task flow and states | `.ai/docs/task-flow.md` |
| Concurrency and locks | `.ai/docs/multi-agent.md` |
| Roles and parallel playbooks | `.ai/docs/orchestration.md` |
| Interrupted work and repair | `.ai/docs/recovery.md` |
| Artifact quarantine | `.ai/docs/artifact-hygiene.md` |
| Conventions and naming | `.ai/docs/conventions.md` |
| Roles | `.ai/agents/` |
| Task store | `.ai/tasks/` |
| Specs | `.ai/specs/` |
| Prompt bodies | `.ai/prompts/` |
| Tool wiring | `.ai/adapters/` |
| CLI | `.ai/scripts/ai` / `.ai/scripts/ai.cmd` |
| Transient state | `.ai/runtime/` |

## Commands

```sh
ai doctor
ai status
ai task new "<title>"
ai task ready
ai task next --agent <name>
ai task claim <id> --agent <name>
ai task release <id> --agent <name>
ai task review <id> --agent <name>
ai task done <id> --agent <name>
ai task block <id> --agent <name> --reason "<why>"
ai task unblock <id> --agent <name>
ai lock acquire <resource> --agent <name> --task <id>
ai lock release <resource> --agent <name>
ai checkpoint <id> --agent <name> --next "<step>"
ai handoff <id> --agent <name> --reason "<why>"
ai resume <id>
ai recover [--apply]
ai git begin --agent <name> --task <id>
ai git end --agent <name>
ai git setup
ai git start --task <id> --agent <name> --type <type>
ai git commit --task <id> --agent <name> --type <type> --message "<subject>"
ai git finish --task <id> --agent <name>
ai git verify --strict
ai artifact put <path> --reason "<why>"
ai check
```

For branch naming, commit trailers, and reviewer merge rules, follow
`docs/git-workflow.md`.

If `ai` is unavailable, follow the same protocol by editing files directly. The
state machine and lock file format are documented; do not invent a shortcut.
