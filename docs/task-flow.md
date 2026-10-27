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
| `review` | Implementation done; independent review needed. | implementer |
| `blocked` | Waiting on a human or another task; reason in the log. | owner |
| `done` | Archived to `tasks/done/`; lock released. | `ai task done` |

`done` tasks are immutable. If behavior must change after `done`, create a new
task and link the old one under `## Notes`.

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

- Read the spec, if one exists.
- Acquire locks for any shared subsystem before editing it.
- Keep notes in the task body, never in the project tree.
- Run `ai check --fast` while iterating.
- Checkpoint at milestones and before the context window fills
  (`ai checkpoint 0001 --agent implementer --next "..."`).

### 4. Block, hand off to review, or hand off to another agent

- **Blocked:** `ai task block 0001 --agent implementer --reason "needs API key"`.
  Unblock with `ai task unblock 0001 --agent <name>`.
- **Review:** set `status: review`, release the task lock, and leave the diff and
  the spec path in the log. The reviewer must be a different session.
- **Context limit:** `ai handoff 0001 --agent implementer --reason "context
  limit"`. The marker and checkpoint let a fresh session run `ai resume 0001`.

### 5. Verify and finish

```sh
ai check
ai task done 0001 --agent qa
```

Attach the check command and its result to the task before marking it done.

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
