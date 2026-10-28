# Task flow

Every piece of work is a task file under `tasks/active/`. Tasks are Markdown
with YAML-like front matter. The front matter is the state; the body is the
story.

## States

```
todo ──claim──> in_progress ──handoff──> review ──verify──> done
  ^                  |                     |
  |                  v                     |
  +────release───────+──────blocked────────+
```

| Status | Meaning | Set by |
|--------|---------|--------|
| `todo` | Ready, unclaimed. | author |
| `in_progress` | An agent owns it and holds `task-<id>`. | `ai task claim` |
| `review` | Implementation done; independent review needed. | `ai task review` |
| `blocked` | Waiting on a human or another task; reason in the log. | owner |
| `done` | Archived to `tasks/done/`; lock released. | `ai task done` |

`done` tasks are immutable. If behavior must change after `done`, create a new
task and link the old one under `## Notes`.

An operator can permanently remove an unwanted task with `ai task discard
<id>`. This requires an interactive terminal, an exact typed confirmation, and
no task lock. It removes only the task, its matching linked spec, and its
checkpoint/handoff state; it does not delete code, commits, or branches. Agents
must not run this command unless the user explicitly requests the discard.

To clear the whole workspace ledger and runtime state, an operator can run
`ai reset --hard`. It requires all lock files to be gone and the exact
interactive phrase `reset .ai hard`. It preserves the framework, configuration,
host Git history and branches. It removes project task/spec records and numbered
ADRs (`NNNN-*.md`) while preserving `docs/decisions/README.md`, `TEMPLATE.md`,
`.gitkeep` and unrelated files. State-changing CLI commands serialize against
the reset. Agents must not run it without an explicit user request.

## Front matter

```yaml
---
id: 0001
title: Add invoice export
status: todo
owner: null
priority: medium          # low | medium | high
spec: null               # path or id, when a spec exists
depends_on: null         # comma-separated task ids that must be done first
created: 2026-10-27T18:30:00Z
updated: 2026-10-27T18:30:00Z
lock: null               # task-0001 while claimed
---
```

The CLI rewrites this block; do not hand-edit fields that the CLI maintains.

## Lifecycle

### 1. Create

```sh
ai task new "Add invoice export" --priority high --spec specs/active/0001-export.md
ai task new "Add invoice import" --depends-on 0001
```

The id is allocated under the `tasks.index` lock, so two agents cannot receive
the same id. The file is created in `tasks/active/` and `tasks/BOARD.md` is
refreshed.

`depends_on` prevents parallel agents from starting work that needs unmerged
predecessors.

### 2. Claim

```sh
ai task claim 0001 --agent implementer
```

This atomically acquires `task-0001`, sets `owner` and `status: in_progress`,
and appends to the log. If another agent holds the lock, the claim is refused.
Read the holder's agent, task and start time from the error before retrying.

A claim is also refused when the task is `blocked` or when a task in
`depends_on` is not `done`. `--force` overrides both; use it only with a reason
recorded in the log.

Workers do not need to pick an id by hand:

```sh
ai task ready                 # todo + dependencies done + no live task lease
ai task next --agent worker1  # atomically claim the best ready task
```

`next` sorts by priority and skips anything a concurrent agent claimed first. If
nothing is ready it exits nonzero and prints why each candidate is waiting.

### 3. Work

- Gitflow is required for every task that changes files unless the user
  explicitly asks not to use Git. Run `ai git setup` before file-changing work;
  it initializes Git and its base branches when missing. After claiming, run
  `ai git start --task <id> --agent <name> --type <type>` before the first edit.
  Stop if setup or branch creation fails. Read-only tasks need no branch. If Git
  reports dubious ownership, ask the user to approve trusting only this exact
  checkout. See `docs/git-workflow.md`.
- Read the spec, if one exists.
- Acquire locks for any shared subsystem before editing it.
- Keep notes in the task body, never in the project tree.
- Run `ai check --fast` while iterating.
- Checkpoint at milestones and before the context window fills
  (`ai checkpoint 0001 --agent implementer --next "..."`).

### 4. Block, hand off to review, or hand off to another agent

- **Blocked:** `ai task block 0001 --agent implementer --reason "needs API key"`.
  Unblock with `ai task unblock 0001 --agent <name>`.
- **Review:** the owner runs `ai task review <id> --agent <name>` and then
  `ai task release <id> --agent <name>`. This preserves `review` while freeing
  the claim for a different session. Leave the diff and spec path in the log.
- **Context limit:** `ai handoff 0001 --agent implementer --reason "context
  limit"`. The marker and checkpoint let a fresh session run `ai resume 0001`.

### 5. Verify and finish

```sh
ai check
ai task done 0001 --agent qa
```

In a Git repository, stage only owned files, run `ai git verify --strict`, and
commit with `ai git commit`. The implementer submits and releases the task for
independent review; a separate reviewer runs `ai git finish` before the task is
marked done. Attach the check command and its result to the task.

## Specs

A behavior change needs a spec in `specs/active/` with:

- **Intent** — the problem, in one paragraph.
- **Behavior** — what changes and what is explicitly preserved.
- **Acceptance criteria** — testable statements, each mapped to evidence.
- **Out of scope** — what this work will not do.

Copy `specs/TEMPLATE.md`. When the work is shipped, move the spec to
`specs/done/` and treat it as immutable.

## Human gates

- **lite** — spec approval is a quick yes/no; plan approval is required.
- **strict** — spec approval, plan approval, finding triage and ship decision
  are all human gates.

A gate is recorded in the task or spec (`Approved by / on`) so the next role can
check it without asking.

## Evidence

Evidence is a pointer, not a dump. Reference the test name and the command:

```
Evidence: `ai check` -> 0 errors, 0 warnings; test `test_invoice_export`.
```

Do not commit raw output files; they are noise and belong in the task log at
most.
