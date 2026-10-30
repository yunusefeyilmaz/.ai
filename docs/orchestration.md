# Orchestration — running several agents safely

Multiple agents do not fail because they are slow. They fail because they share
mutable state without a protocol. The workspace makes that state explicit:
tasks, locks, checkpoints and handoffs are files that every agent can read.

Use this document with `docs/multi-agent.md` (the lock mechanics) and
`docs/recovery.md` (interrupted work).

## Roles

Role cards live in `agents/`. A role is a **session mode**, not a permanent
identity. One tool can play different roles in different sessions.

| Role | Owns | Must not | Typical output |
|------|------|----------|----------------|
| Orchestrator | Triage, task creation, dependency order, assignment | Write product code; edit task bodies owned by workers | Board, task files, assignments |
| Planner | Spec, acceptance criteria, plan, risks | Implement | `specs/active/*.md`, plan in task |
| Implementer | One task, its files, tests | Review its own work; touch other tasks | Code, tests, task log |
| Reviewer | Diff vs spec, defects, security, scope | Edit the implementation | Review report, PASS/FAIL |
| QA | End-to-end verification, regression | Redefine the spec silently | Test evidence, `ai check` output |

In `strict` mode, humans gate spec, plan and triage. In `lite` mode the same
artifacts exist but are not blocking. The mode does not change the file format.

## Topologies

### 1. Single agent

One session does everything, checkpointing at milestones. Best default. Add
review only when the change is risky.

### 2. Planner + implementer + reviewer

Three sessions, one task.

1. Planner writes the spec and plan, releases the task.
2. Implementer claims, builds, verifies, moves the task to `review`.
3. Reviewer (fresh context) reads the spec and diff, then passes or fails.

The producer never reviews its own work. The reviewer writes findings into the
task or a review file; it does not edit the code.

### 3. Parallel implementers

Only for genuinely independent tasks. Each agent needs a separate working tree:

```sh
git worktree add ../proj-a -b task/0007-export
git worktree add ../proj-b -b task/0008-import
```

Each worktree has its own `.ai/runtime/` (locks and checkpoints are local, not
shared). Task files are committed to the branch, so ownership travels with the
work. Merge after review. Without worktrees, agents share one index and one
checkout; use `ai git begin/end` and expect conflicts.

### 4. Orchestrator + workers

The orchestrator only triages and assigns. Workers never edit `tasks/BOARD.md`
or tasks they do not own. Use `depends_on` to encode order:

```sh
ai task new "Add CSV export" --depends-on 0007
```

`ai task claim` refuses while the dependency is not `done`. Workers start with
`ai task ready` or `ai task next --agent <name>` instead of choosing an id, so a
blocked task never enters their queue. The orchestrator writes tasks and specs;
it does not implement. Prompts: `prompts/orchestrator.md`,
`prompts/worker.md`.

## Lock protocol

Acquire in a fixed order to avoid deadlocks:

1. Task lock (`ai task claim`) when you start.
2. File/subsystem locks (`ai lock acquire`), in sorted order.
3. `@git/index` (`ai git begin`) only around staged operations.

Release in reverse order. Never hold two task locks. Never acquire a file lock
for a task you do not own. A live lock is a refusal; do not delete it.

Overlap is intentional: `src/billing` conflicts with `src/billing/invoice.py`.
Globs work: `src/*.ts` conflicts with `src/a.ts` and with `src`.

```sh
ai lock acquire src/billing --agent impl-a --task 0007
ai lock acquire src/import  --agent impl-b --task 0008
ai git begin --agent impl-a --task 0007
git add src/billing && git commit -m "feat(billing): csv export"
ai git end --agent impl-a
```

## Decomposing work

Good tasks are:

- independently claimable,
- independently verifiable,
- small enough for one context window,
- explicit about files they touch.

Split by **seam**, not by layer. "Billing export" is better than "all models",
"all services", "all tests". If two tasks must edit the same file in the same
week, either serialize them with `depends_on` or give one task both changes.

### The ready queue

`depends_on` is only useful if workers respect it mechanically:

```sh
ai task ready          # todo + all dependencies done + no live task lease
ai task next --agent <name>
```

`ready` lists only tasks that can start now; `next` atomically claims the
highest-priority one. A worker that sees "No ready task" must stop or help with a
different role, not force a blocked task. This is the coordination point between
the window that creates tasks and the windows that consume them.

Every behavior change gets a spec. Acceptance criteria are testable sentences:

```markdown
- [ ] GET /invoices/export returns text/csv with a header row.
- [ ] An invoice with no lines exports as a row with zero total.
- [ ] The endpoint requires the `billing:read` scope.
```

## Handoff between roles

A handoff is a checkpoint plus a marker plus a prompt. Nothing relies on chat
history.

```sh
ai checkpoint 0007 --agent impl-a --reason handoff \
  --objective "..." --status "..." --next "..." \
  --files src/billing/export.py --verification "npm test: 41 passed"
ai handoff 0007 --agent impl-a --reason "ready for review"
```

The next role starts with `ai resume 0007`, verifies drift, then claims or
heartbeats the lock. Reviewers usually do **not** claim the task; they read it and
write a verdict. If the review fails, the implementer reclaims and fixes.

## Git index contention

`git add` is not concurrency-safe. Two agents staging at once can stage each
other's files or corrupt the index lock.

- Preferred: separate worktrees (no shared index).
- Otherwise: `ai git begin` before staging, `ai git end` after committing.
- Keep the git lock short-lived (`--ttl 300`). Never hold it while running tests.
- Before committing, `ai git verify --strict` fails if a staged path has no
  held file lock.

Never force-push a branch another agent is reviewing. Never commit `runtime/`.

## Human gates

`strict` mode requires a human at three points:

| Gate | Artifact | Question |
|------|----------|----------|
| Spec | `specs/active/<id>-*.md` | Is this the right problem and the right criteria? |
| Plan | Task "Plan" section | Is this the right approach and file set? |
| Triage | Board / task priority | Is this the right order? |

Record approval in the task log with who and when. A gate is not a review; it is
a decision to spend effort.

## Monitoring a fleet

A coordinator checks, in order:

```sh
ai status --json          # tasks, owners, locks, checkpoints, handoffs
ai task list --all
ai lock status --json
ai check --strict
```

Signals that something is wrong:

- `in_progress` with no checkpoint for over `handoff.warnAfterMinutes`
- owner without a lock, or lock with a different owner
- a handoff marker with no fresh checkpoint
- two tasks touching the same paths without `depends_on`
- a done task still holding a lock
- repeated `--force` claims (a sign of abandoned work)

Prefer `ai recover --apply` for structural issues and `ai resume` for context
issues. Do not "clean up" by deleting task files.

## Prompt templates

### Orchestrator triage

```text
Read .ai/AGENTS.md, .ai/GUIDE.md and .ai/docs/orchestration.md.
Run `.ai/ai status --json`. Do not write product code.
Split the goal into independent tasks with testable acceptance criteria.
Create them with `.ai/ai task new`, set `--depends-on` where order matters,
and write each spec in .ai/specs/active/. Refresh the board and stop.
```

### Implementer

```text
Read .ai/AGENTS.md, the task and its spec. Claim it with
`.ai/ai task claim <id> --agent <name>`. Acquire locks for the files you
will touch. Implement only the acceptance criteria, with tests. Run
`.ai/ai check --fast` as you go. Checkpoint at milestones and before your
context fills. When green, run `.ai/ai check --strict`, record the output
in the task, and move it to review.
```

### Reviewer

```text
You are the reviewer. Read the spec, the task and `git diff <base>...HEAD`.
For each acceptance criterion, cite file:line evidence. Look for missing tests,
security issues, scope creep and broken contracts. Do not edit code. Write a
PASS/FAIL verdict with concrete fixes, then run `.ai/ai check --strict`.
```

### Handoff

```text
Your context is nearly full. Do not start new work. Run
`.ai/ai checkpoint <id> --agent <name> --reason context --percent 85`
with a complete brief for a stranger, then `.ai/ai handoff <id> --agent
<name> --reason "context limit"`. Stop. The next session will run `ai resume`.
```

## Anti-patterns

| Anti-pattern | Why it fails | Instead |
|--------------|--------------|---------|
| Two agents editing one task | Lost updates, conflicting logs | One owner; handoff explicitly |
| Deleting a lock to "unblock" | Two writers, silent corruption | Wait, heartbeat, or `--force` after checking |
| Reviewing your own work | Blind spots | Fresh session with spec + diff |
| Chat-only decisions | Lost on context end | Write to task, spec or ADR |
| Giant task | Cannot finish in one context | Split by seam |
| Layer-based split | Everyone edits the same files | Split by feature boundary |
| Pasting files into prompts | Burns context, goes stale | Point at paths; let the agent read |
| "Done" without `ai check` | Unverifiable | Attach command output |
| Committing `runtime/` | Lock/checkpoint noise | Keep it ignored |
| Orchestrator coding | No one is coordinating | Keep roles separate |

## Checklist before starting a fleet

- [ ] Root adapters and ignore rules created locally (`ai adopt --check` passes).
- [ ] `ai doctor --strict` green on a clean checkout.
- [ ] Each task has acceptance criteria and a known file surface.
- [ ] Dependencies encoded with `depends_on`.
- [ ] One worktree per parallel implementer (preferred).
- [ ] Reviewer sessions are separate from producers.
- [ ] Everyone knows: claim first, lock files, checkpoint before context ends.
