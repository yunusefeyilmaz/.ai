# Recovery — interrupted work and inconsistent state

AI sessions end abruptly: context limits, crashes, closed terminals, rate limits,
a human stopping mid-edit. The workspace must make that normal, not exceptional.

The rule: **state on disk beats memory**. A checkpoint is the handoff artifact. A
resume brief is how the next session starts. Everything else is repair.

## What survives what

| Event | Survives | Lost | Recovery |
|-------|----------|------|----------|
| Context window fills | Task file, checkpoint, locks, git state | Chat history, unstated reasoning | `ai resume <id>` |
| Process killed | Same | In-flight command output | `ai recover`, `ai check` |
| Machine crash / power loss | Committed files; atomic writes | Unflushed buffers | `ai recover`, `ai check` |
| Network/tool outage | Local files | Remote sync | Work locally; sync later |
| Two agents on one task | Task file, one lock | Loser's uncommitted edits | Refused claim; rebase/review |
| Agent forgets to checkpoint | Task file, git | Context | Reconstruct from `git diff`, task log |
| Task file corrupted | Other tasks | That file | Restore from git or `tasks/done/` |
| Stale lock | Lock JSON | Nothing | Wait for TTL, heartbeat, or `--force` |

## Checkpoint vs handoff vs task log

- **Task log** (`tasks/active/<id>-*.md`) is a chronological trail. Cheap, always
  append. Not enough to resume alone.
- **Checkpoint** (`runtime/state/checkpoints/<id>.md` + `.json`) is a snapshot
  written for a stranger. Replaces the previous one, archives the old copy.
- **Handoff marker** (`runtime/state/handoff/<id>.json`) says "someone must pick
  this up now". `ai check` warns when a marker has no checkpoint or the
  checkpoint is older than the marker.

The JSON sidecar stores the branch, HEAD, dirty files, and per-file fingerprints
(sha256, or size + mtime for files over 5 MB). `ai resume` diffs the current repo
against it and reports **drift**.

## The context-limit playbook

Budget thresholds live in `config/workspace.json`:

```json
"budget": { "contextTokens": 200000, "warnAtPercent": 70, "checkpointAtPercent": 85 }
```

1. **70%** — finish the current small step. Do not start a refactor.
2. **85%** — checkpoint even mid-step. Say exactly where it stopped.
3. **Before the window closes** — handoff. Stop cleanly.

```sh
ai checkpoint 0007 --agent codex --reason context --percent 85 \
  --objective "Export invoices as CSV" \
  --status "Parser done; writer fails on empty rows" \
  --done "CSV parser + tests (12 passing)" \
  --in-progress "writer.py line 84: KeyError on missing vat_id" \
  --next "1. Handle missing vat_id. 2. Add empty-row test. 3. Run npm test." \
  --decisions "Use csv module; no dependency" \
  --do-not "Do not rewrite parser" \
  --files src/export/parser.py,src/export/writer.py \
  --verification "npm test: 12 passed, 1 failing"

ai handoff 0007 --agent codex --reason "context limit"
```

`ai handoff` prints the resume prompt. Paste it into the next session. That
session starts with `ai resume 0007`.

If a session dies **without** a checkpoint, reconstruct from the outside:

```sh
git status
git diff
git log --oneline -10
ai task show 0007
```

Write a checkpoint from what the repository proves, not from what you remember.
Mark uncertain items as open questions.

## Drift

Drift is any difference between the checkpoint and the current repo:

- commits landed since the checkpoint (`commits_since`)
- files that changed, disappeared, or cannot be compared
- a different branch or detached HEAD
- a dirty tree

```sh
ai resume 0007          # human-readable drift
ai resume 0007 --json   # machine-readable
```

Drift is information, not failure. A teammate may have changed the same area. Do
not blindly apply the checkpoint's next steps: re-read the changed files first.
If the drift invalidates the plan, write a new checkpoint before continuing.

## Missing files and `ai doctor --fix`

A crash, a partial copy or a bad merge can remove runtime directories or
`config/workspace.json`. `ai doctor` names each problem and the next safe action;
`ai doctor --fix` performs the repairs that cannot lose data:

| Missing | Repair |
|---------|--------|
| runtime directories and keep files | recreated |
| `config/workspace.json` | written from the defaults |
| subfolder adapter pointers and ignore rules | written by the same code as `ai adopt` |

It never rewrites an invalid config, removes a lock, edits a task or spec, or
touches Git. Everything else stays as a finding and the command exits 1. Use
`--json` to get `fixes` and the remaining `findings`.

## Inconsistent state and `ai recover`

`ai check` reports structural problems. `ai recover` detects and can repair them.

```sh
ai recover            # dry run, lists FIND actions
ai recover --apply    # applies FIX actions
ai recover --json     # machine-readable
```

Repairs:

| Inconsistency | Detection | Repair |
|---------------|-----------|--------|
| Status `done`, file in `active/` | task folder vs status | move to `done/` |
| File in `done/`, status not `done` | folder vs status | set status `done` |
| Owner set, no live task lock | task meta vs locks (stale = absent) | clear owner; `in_progress` -> `todo` |
| Lock held, owner empty | task meta vs locks | restore owner from lock |
| Done task still locked | status vs locks | delete task lock |
| Orphan task lock | lock has no task file | delete lock |
| Stale lock | TTL exceeded | delete lock |
| Handoff marker for gone/done task | marker vs task store | delete marker |

`ai recover --apply` is idempotent: run it twice, the second run finds nothing.
It never edits product code.

## Corrupted or hand-edited files

All CLI writes are atomic (temp file + replace), so partial JSON is rare. If you
hand-edit:

- Task front matter is `key: value` lines between `---` fences. Keep `id`,
  `title`, `status`, `owner`, `updated`.
- A lock is a JSON object with `resource`, `agent`, `task`, `started_at`,
  `updated_at`, `ttl_seconds`.
- A checkpoint is a task-shaped Markdown file plus its `.json` sidecar.

If a file is unparseable, `ai check` reports it. Restore from git:

```sh
git checkout -- .ai/tasks/active/0007-export-invoices.md
```

If the task was never committed, recreate it with `ai task new` and copy the body.

## Two agents, one task

The task lock is the arbiter. The loser's claim is refused; it must not edit the
task or the locked files. If the loser already edited shared files, treat them as
suspect: review the diff, keep or revert deliberately.

Never delete a live lock because it is inconvenient. If the owner is gone, the
options are, in order:

1. `ai lock heartbeat <resource> --agent <owner>` if you are resuming that agent.
2. Wait for `locks.staleAfterSeconds`.
3. `ai lock release task-<id> --force` after confirming no process is working.
4. `ai recover --apply` for structural leftovers.

## Git-level recovery

- **Staged by the wrong agent:** `ai git verify` lists staged paths with no held
  lock. Unstage only those: `git restore --staged <path>`.
- **Conflict during a handoff:** resolve like any merge; then write a checkpoint
  describing the resolution so the next agent does not reopen it.
- **Accidental commit of runtime state:** `runtime/` is gitignored. If one slips
  in, remove it from the index (`git rm --cached`) and commit the fix.
- **Secrets:** rotate first, then clean history. `ai check` only warns; it cannot
  undo exposure.

## Escalation

Stop and ask a human when:

- the spec itself is ambiguous or contradictory;
- recovery requires deleting committed work;
- a secret was committed;
- two agents produced incompatible plans for the same task;
- `ai check` fails for a reason not covered by the spec.

Record the escalation as a blocked task (`ai task block <id> --agent <name>
--reason "..."`) or an open question in the checkpoint. Do not guess silently.
