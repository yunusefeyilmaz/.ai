# Operator's handbook

`README.md` says what this is. This file says how to operate it, whether you are
the human supervising a session or the agent doing the work.

The handbook assumes the CLI is available as `ai`. In a subfolder install that
means `.ai/scripts/ai` (`.ai\scripts\ai.cmd` on Windows); you can add
`.ai/scripts` to `PATH`. Without Python, every step still works by editing files.

## Three concepts

| Concept | What it is | Where it lives | Lifetime |
|---------|------------|----------------|----------|
| **Task** | The unit of intent, with acceptance criteria and a log | `tasks/active/<id>-<slug>.md` | Until archived |
| **Lease** | A time-bounded claim on a task or path | `runtime/locks/*.lock` | TTL, refreshed by heartbeat |
| **Checkpoint** | A structured snapshot for resuming work | `runtime/state/checkpoints/<id>.md` | Until replaced or the task ends |

A task is durable and committed. A lease is transient and local to a checkout. A
checkpoint is transient too, but it is the only thing that survives a context
reset with enough detail to continue.

Two rules follow from this:

1. If a fact matters to the next session, put it in the task, the spec, a
   checkpoint or an ADR — not in chat.
2. A lease is a refusal, not a suggestion. Expired leases are recoverable; live
   ones are not yours.

## Installing

### Root template

Copy the repository contents into the project root. `AGENTS.md` at the root is
already the entry point, so nothing needs to run. The CLI notices that the
workspace is the project root.

### Subfolder

```sh
git clone https://github.com/yunusefeyilmaz/.ai.git .ai
.ai/scripts/ai adopt
```

`adopt` writes managed pointer blocks to the root files that tools auto-load:

| File | Read by |
|------|---------|
| `AGENTS.md` | Codex and generic agents |
| `CLAUDE.md` | Claude Code |
| `.cursor/rules/ai-workspace.mdc` | Cursor |
| `.github/copilot-instructions.md` | GitHub Copilot |

Commit them once. Every later clone is then self-wiring. Useful variants:

```sh
ai adopt --check     # non-zero if a pointer is missing (CI guard)
ai adopt --print     # bootstrap prompt for a chat-only tool
ai adopt --ci        # add .github/workflows/ai-check.yml as well
```

The pointer block is delimited by `<!-- ai-workspace:start -->` and
`<!-- ai-workspace:end -->`, so re-running `adopt` is safe. `--force` rewrites
it.

## First pass: clone to verified change

This is the smallest complete cycle. Run it once on a toy task before using the
workspace on real work.

```sh
# 1. Confirm the workspace is coherent
ai doctor
ai check --no-commands

# 2. See what exists
ai status

# 3. Create the task and its acceptance criteria
ai task new "Export invoices as CSV" --priority high
cp specs/TEMPLATE.md specs/active/0001-export-invoices.md
$EDITOR specs/active/0001-export-invoices.md

# 4. Become the owner
ai task claim 0001 --agent implementer

# 5. Lease the paths you intend to change
ai lock acquire src/billing --agent implementer --task 0001

# 6. Work in small increments
ai check --fast

# 7. Save your position before the context fills
ai checkpoint 0001 --agent implementer --percent 70 \
  --next "write the CSV writer" --files src/billing/export.py

# 8. Prove it, then close it
ai check --strict
ai task done 0001 --agent implementer
```

Steps 3 and 8 are the ones agents skip when unsupervised. The workspace makes
skipping visible: `ai check` warns about work in progress with no fresh
checkpoint, about ownership that disagrees with leases, and about tasks whose
folder and status diverge.

## Command surface

Use `ai <group> --help` for every flag. The groups are stable; the shortcuts are
the ones below.

### Workspace health

```sh
ai doctor [--strict] [--json]
ai check [--fast] [--strict] [--json] [--no-commands]
ai status [--json]
ai capabilities
```

`--strict` promotes warnings to failures. CI runs `doctor --strict` and
`check --strict`. `--fast` runs only checks marked fast in
`config/workspace.json`; `--no-commands` skips configured shell commands.

### Task ledger

```sh
ai task new "<title>" [--priority low|medium|high] [--spec <path>] [--depends-on 0002]
ai task list [--all] [--json]
ai task show <id> [--json]
ai task ready [--json]                 # claimable: todo, deps done, no live lease
ai task next --agent <name> [--json]   # atomic claim of the best ready task
ai task claim <id> --agent <name> [--force]
ai task release <id> --agent <name> [--force]
ai task block <id> --agent <name> --reason "<why>"
ai task unblock <id> --agent <name>
ai task done <id> --agent <name> [--force]
```

Claim rules:

- A `blocked` task cannot be claimed.
- A task whose `depends_on` entries are not `done` cannot be claimed.
- `--force` overrides both; record why in the task log.
- Re-claiming with the same agent name refreshes the lease instead of failing.
- `done` archives the file and makes it immutable.

### Leases

```sh
ai lock acquire <path-or-glob> --agent <name> --task <id> [--ttl s] [--force]
ai lock release <path-or-glob> --agent <name> [--force]
ai lock heartbeat <path-or-glob> --agent <name>
ai lock status [--json]
```

Resources are repo-relative. Overlap is a conflict:

```sh
ai lock acquire src/billing            --agent a --task 0001
ai lock acquire src/billing/writer.py  --agent b --task 0002   # refused
ai lock acquire "src/*.ts"             --agent b --task 0002   # may be refused
ai lock acquire project                --agent a --task 0001   # everything
```

`@git/index` is reserved for `ai git begin`. `tasks.index` is reserved for id
allocation. Do not hand-edit or delete live lease files; see the failure table
below.

### Continuation

```sh
ai checkpoint [id] --agent <name> [narrative flags] [--reason ...] [--percent N]
ai handoff    [id] --agent <name> --reason "<why>"
ai resume     [id] [--json]
ai brief      [id] [--max-chars N] [--json]
```

Narrative flags: `--objective`, `--status`, `--done`, `--in-progress`, `--next`,
`--decisions`, `--do-not`, `--questions`, `--files`, `--files-text`,
`--verification`. Omitted flags are inherited from the previous checkpoint, not
erased.

### Git coordination

```sh
ai git begin  --agent <name> --task <id> [--ttl 300]
ai git end    --agent <name> [--force]
ai git verify [--strict] [--json]
```

Use `begin` immediately before staging and `end` immediately after committing.
`verify` checks that every staged path is covered by a held file lease. Better
than a global index lease: give each parallel agent its own `git worktree`.

### Artifacts and repair

```sh
ai artifact put <path> --reason "<why>" --agent <name>
ai artifact list [--json]
ai artifact clean --all
ai recover [--apply] [--json]
ai clean [--stale-locks] [--logs]
```

`recover` is safe to run at any time; without `--apply` it only reports.

## Leases in practice

A lease file is a JSON object. The CLI serializes acquisition through a short
mkdir mutex, then scans for overlapping resources before creating the file with
`O_CREAT | O_EXCL`.

```json
{
  "resource": "src/billing",
  "agent": "implementer",
  "task": "0001",
  "host": "workstation",
  "pid": 4812,
  "started_at": "2026-10-27T18:30:00Z",
  "updated_at": "2026-10-27T18:31:10Z",
  "ttl_seconds": 1800
}
```

Staleness is calculated from `updated_at` and `locks.staleAfterSeconds`. The PID
is diagnostic only: a task claim must outlive the CLI process that created it.
Long work refreshes the lease:

```sh
ai lock heartbeat task-0001 --agent implementer
ai lock heartbeat src/billing --agent implementer
```

Acquisition order to avoid cycles:

1. Task lease (`ai task claim`).
2. File leases, in lexical order.
3. `@git/index`, for the shortest possible window.

Release in reverse. Never hold two task leases.

## Context resets

The budget is configured in `config/workspace.json`:

```json
"budget": { "contextTokens": 200000, "warnAtPercent": 70, "checkpointAtPercent": 85 }
```

1. **70%** — stop opening new fronts. Finish the current small step.
2. **85%** — checkpoint, even mid-step. State precisely where execution stopped.
3. **Before the window closes** — handoff and stop.

A checkpoint is written for someone with none of your context. Include:

- the objective and why it matters;
- what is true now (branch, error, failing test);
- finished work with evidence;
- the exact in-progress step and its stopping point;
- ordered next actions;
- decisions, rejected approaches and constraints;
- files touched and why;
- commands already run and what they returned.

Do not write secrets or personal data into a checkpoint. Do not assume the next
agent can see this conversation.

```sh
ai checkpoint 0007 --agent codex --reason context --percent 85 \
  --objective "Export invoices as CSV" \
  --status "writer raises KeyError on missing vat_id" \
  --done "parser and 12 tests" \
  --in-progress "writer.py:84, empty-row branch" \
  --next "1. handle missing vat_id 2. add empty-row test 3. npm test" \
  --decisions "stdlib csv only" \
  --do-not "do not rewrite the parser" \
  --files src/export/writer.py \
  --verification "npm test: 12 passed, 1 failing"

ai handoff 0007 --agent codex --reason "context limit"
```

The handoff writes `runtime/state/handoff/0007.json` and prints the prompt for
the next session. That session runs:

```sh
ai resume 0007
```

`resume` prints the checkpoint, the saved next step, a drift report (commits and
files changed since the snapshot), and a ready prompt. Treat drift as a warning,
not a failure: re-read the changed files before following the old plan.

## Parallel work

The safe default is one agent, one task. When that is too slow:

| Situation | Arrangement |
|-----------|-------------|
| Independent tasks | One `git worktree` per agent, one task each |
| One task, several roles | Planner, implementer and reviewer as separate sessions |
| Large initiative | An orchestrator creates tasks and never edits code |
| Same file, different tasks | Serialize with `depends_on` or merge into one task |

Rules that matter more than tooling:

- The producer is not the reviewer. The reviewer receives the spec and the diff.
- A worker never edits a task it does not own, including `tasks/BOARD.md`.
- A lock is released only by its owner, or after it is provably stale.
- A handoff includes a checkpoint; otherwise the next session is guessing.

Roles and longer playbooks: `docs/orchestration.md`.

### Two-window setup: plan in one, build in another

This is the simplest multi-agent arrangement:

1. **Orchestrator window** (for example Claude Code). Give it the request. It
   reads the workspace, looks for an existing task, and if none matches it
   creates tasks, specs and `depends_on` links. It does not write code.
   Prompt: `prompts/orchestrator.md`.
2. **Worker windows** (for example DeepSeek in another terminal). Each one runs
   `ai task ready`, claims one task with `ai task next --agent <name>`, and
   implements only that task. A task whose dependency is not `done` never
   appears in the ready list and cannot be claimed without `--force`.
   Prompt: `prompts/worker.md`.
3. A third window can be the reviewer. It reads the spec and the diff and does
   not edit code.

The queue is the coordination point: the orchestrator writes it, workers consume
it, and `depends_on` plus leases prevent two windows from starting incompatible
work.

## External assistants

A chat model that cannot open the repository will not discover `.ai/` on its
own. Two options:

1. **Give it repository access** (a coding agent, a GitHub connector, uploads).
   Then point it at `AGENTS.md` and let it read the rest.
2. **Paste a brief.** `ai brief` assembles the rules, the selected task, its
   spec, the last checkpoint and the repository state into one block:

```sh
ai brief                  # latest active task
ai brief 0007             # a specific task
ai brief 0007 --json      # structured form
```

The brief explicitly says the model may not have shell access and must not claim
it ran tests. It should answer with a plan, diffs and commands for a human to
execute. Regenerate the brief after the task or checkpoint changes; do not keep
pasting an old one.

## Failure recovery

| Symptom | First action | If it persists |
|---------|--------------|----------------|
| Claim refused | `ai lock status` | Heartbeat if yours; wait for TTL; `--force` after confirming abandonment |
| `owner` set, no lease | `ai recover` | `ai recover --apply` |
| Done task still leased | `ai recover` | `ai recover --apply` |
| Checkpoint older than handoff | `ai checkpoint <id> --agent <name>` | Re-run `ai handoff` |
| Missing required file | Restore from the template | Do not delete the check |
| Staged path without a lease | `ai git verify` | Lease it or unstage it |
| Watched scratch dir in root | `ai artifact put <path>` | Add the path to `artifacts.watch` |
| Suspected secret in git | Remove and rotate | Clean history separately |
| Corrupt task file | Restore from git | Recreate from `tasks/TEMPLATE.md` |

A stale lease normally expires on its own. Deleting a live one is how two agents
end up writing the same file.

## Prompt library

### Opening a session

```text
This project uses the .ai workspace. Read AGENTS.md, GUIDE.md,
docs/task-flow.md and docs/multi-agent.md. Run `ai status`, choose one task,
claim it with `ai task claim <id> --agent <name>`, and work only on that task.
Checkpoint before your context fills. Do not use the word "done" without `ai check`.
```

### Approaching the context limit

```text
Stop starting new work. Run `ai checkpoint <id> --agent <name> --reason context
--percent 85` and write every section for a stranger: objective, current status,
done with evidence, the exact stopping point, ordered next steps, decisions,
do-not list, files, and commands already run. Then run `ai handoff <id> --agent
<name> --reason "context limit"` and stop.
```

### Picking up a handoff

```text
Run `ai resume <id>`. Read the task, checkpoint and drift report. Verify the
repository yourself before trusting the snapshot. Refresh the claim, then resume
from the first unchecked next step. Do not repeat finished work.
```

### Independent review

```text
You are the reviewer, not the producer. Read the spec, the task and the diff
against the base branch. Check each acceptance criterion with file:line evidence,
then look for missing tests, security problems and scope creep. Do not edit the
implementation. Report PASS or FAIL and run `ai check --strict`.
```

### Repairing a session

```text
Run `ai status --json` and `ai recover`. Explain each finding before applying it.
Apply only repairs you understand with `ai recover --apply`. For abandoned claims,
wait for the TTL rather than deleting a live lease. Re-run `ai check`.
```

## Reference

### Task states

| State | Owner | Meaning |
|-------|-------|---------|
| `todo` | none | Ready to be claimed |
| `in_progress` | set | Being worked on; task lease held |
| `review` | optional | Implementation finished; independent check pending |
| `blocked` | optional | Waiting on a person or another task |
| `done` | none | Archived under `tasks/done/` |

### Config keys

| Key | Purpose |
|-----|---------|
| `mode` | `lite` or `strict` gates |
| `locks.defaultTtlSeconds` | Initial lease duration |
| `locks.staleAfterSeconds` | When a lease may be reclaimed |
| `locks.maxTtlSeconds` | Upper bound for `--ttl` |
| `handoff.warnAfterMinutes` | When `ai check` warns about a stale checkpoint |
| `budget.*` | Context thresholds for checkpointing |
| `artifacts.watch` | Paths that must not appear outside `.ai/` |
| `security.warnTrackedSecrets` | Warn on tracked key-shaped files |
| `checks` | Project commands run by `ai check` |

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Verification failed or an operation was refused |
| `127` | No Python 3 found; use the file protocol |

### File map

| Path | Purpose |
|------|---------|
| `AGENTS.md` | Invariants every session accepts |
| `config/workspace.json` | Mode, leases, budget, watch list, checks |
| `tasks/` | Ledger, template, generated board |
| `specs/` | Acceptance criteria, active and shipped |
| `docs/` | Flow, concurrency, orchestration, recovery, hygiene, decisions |
| `agents/` | Role cards |
| `prompts/` | Prompt bodies |
| `adapters/` | Per-tool wiring |
| `scripts/` | CLI and launchers |
| `runtime/` | Leases, checkpoints, handoffs, artifacts, logs |

## If something looks wrong

- **`ai` missing:** call the launcher path directly or add `.ai/scripts` to
  `PATH`.
- **No Python:** follow `docs/task-flow.md`; keep the JSON lease shape if you
  must edit one by hand.
- **A warning in `ai check`:** warnings are signals. `--strict` turns them into
  failures, which is what CI does.
- **Two agents disagree:** the spec's acceptance criteria and `ai check` win.
  Put the command output in the task.

## Where to read next

| Question | Document |
|----------|----------|
| How do tasks change state? | `docs/task-flow.md` |
| How do leases and TTLs work? | `docs/multi-agent.md` |
| How do I run several agents? | `docs/orchestration.md` |
| How do I recover interrupted work? | `docs/recovery.md` |
| What may exist outside `.ai/`? | `docs/artifact-hygiene.md` |
| What are the naming and commit rules? | `docs/conventions.md` |
| Why was this designed this way? | `docs/decisions/` |
