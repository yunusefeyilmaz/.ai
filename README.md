# .ai

A small, self-contained workspace that lets coding agents share one task ledger,
one set of file leases, and one definition of "finished" — without a server, a
database, or a package install.

Copy it into a repository. An agent can then answer four questions from files
alone: what should I work on, may I touch this file, how do I prove it works, and
where do my notes go. Humans get the same answers, which makes review and
recovery much cheaper.

## The guarantees

- **A durable task ledger.** Every piece of work is a Markdown file with an id,
  owner, status and log. It survives the session that created it.
- **Ownership with leases.** A task claim and any file lock are JSON leases with
  a TTL. A live lease is a refusal; an expired one can be reclaimed.
- **One verification command.** `ai check` is the gate locally and in CI. It
  never depends on an agent's confidence.
- **A place for operational state.** Checkpoints, handoff markers, locks and
  scratch artifacts live under `.ai/runtime/` and never enter the product tree.
- **A continuation record.** If a context window ends, the next session resumes
  from a checkpoint and a drift report instead of from memory.

## Pick an install shape

| Shape         | What you do                                           | Result                                                            |
| ------------- | ----------------------------------------------------- | ----------------------------------------------------------------- |
| **Template**  | Copy this repository's contents into the project root | Works immediately; root `AGENTS.md` is the entry point            |
| **Subfolder** | Clone into `.ai/` and run `ai adopt`                  | `.ai/` and local root pointers are ignored; each clone runs adopt |

The subfolder shape is the common one:

```sh
git clone https://github.com/yunusefeyilmaz/.ai.git .ai
.ai/scripts/ai adopt              # Windows: .ai\scripts\ai.cmd adopt
```

Run `ai start` instead to do this wiring automatically while creating the first
task.

`adopt` writes a managed pointer block into `AGENTS.md`, `CLAUDE.md`,
`.cursor/rules/ai-workspace.mdc` and `.github/copilot-instructions.md`, then adds
those paths and `.ai/` to the host project's `.gitignore`. It creates
`.gitignore` if needed and appends only missing rules. Each clone runs `adopt`
locally. `adopt --check` verifies local pointers and ignore rules;
`adopt --print` emits a bootstrap prompt for tools that cannot read files.

Python is optional. Without it, the same protocol is followed by editing the
Markdown and JSON files directly.

## A short walkthrough

From a clone to a claimed task:

```sh
ai start --agent <your-name>
```

`ai start` creates missing runtime state, wires the local pointers in a subfolder
install, detects the Git layout (running `ai git setup` when the repository
already has a commit), creates the starter task with its spec, and claims it. It
prints only the commands that come next. On a project with existing tasks it
never adds a demo task; `--no-demo` also skips it on a fresh workspace.

Then run the loop:

```sh
ai git start --task 0001 --agent <your-name> --type feature
# ... edit the task's files ...
git add <files-you-own>
ai git verify --strict
ai git commit --task 0001 --agent <your-name> --type feat --message "add CSV export"
ai checkpoint 0001 --agent <your-name> --percent 70 --next "write the CSV writer"
ai check --strict                          # required before review
ai task review 0001 --agent <your-name>    # records review state
ai task release 0001 --agent <your-name>   # reviewer takes over
ai git finish --task 0001 --agent reviewer # guarded no-ff merge
ai task done 0001 --agent reviewer         # archives after verification
```

If the session ends before `done`, run `ai handoff`; a fresh session starts with
`ai resume` and a drift report. The full command surface is in `GUIDE.md`.

Every file-changing task must follow the local Gitflow loop unless the user
explicitly asks not to use Git. `ai git setup` initializes Git if needed and
creates a baseline for the branches. With no existing commit, it previews all
non-ignored project files and asks before creating the initial commit. Start
from a task branch on `develop` (hotfixes from `master`), use
task/agent commit trailers, and have a separate reviewer merge with guarded
no-ff. Agents must start the task branch before editing. Read-only work needs no
branch. Ask approval if Git rejects the checkout's ownership. See
[`docs/git-workflow.md`](docs/git-workflow.md)
for setup, branch naming and the full review flow.

When `.ai` itself is a standalone Git checkout, setup uses that checkout as the
project root. When `.ai` is adopted inside a host project, setup uses the host
root. New repositories start on the configured production branch regardless
of Git's default branch name; unborn branch names are not treated as
commit-backed Gitflow bases.

## How the pieces fit

```
your-project/
├── <product code>
└── .ai/
    ├── AGENTS.md        entry contract for every agent
    ├── GUIDE.md         operator's handbook
    ├── config/          mode, TTLs, budgets, watch list, project checks
    ├── tasks/           task ledger: active/, done/, generated BOARD.md
    ├── specs/           acceptance criteria per behavior change
    ├── docs/            architecture, flow, concurrency, recovery, ADRs
    ├── agents/          role cards
    ├── prompts/         reusable prompt bodies
    ├── adapters/        per-tool pointers
    ├── scripts/         stdlib-only Python CLI + launchers
    ├── tests/           CLI integration tests (stdlib unittest)
    └── runtime/         leases, checkpoints, handoffs, artifacts, logs
```

The split matters: `.ai/` is agent territory, the rest is product territory.
`ai adopt` is the explicit operator action that creates ignored local pointers
and ignore rules at the project root.

## When something breaks

`ai doctor` prints a `fix:` line under every finding it knows how to repair.
When the workspace is missing regenerable state, let it do the safe part:

```sh
ai doctor --fix
```

`--fix` recreates missing runtime state, writes `config/workspace.json` when it
is absent, and wires missing subfolder adapters and ignore rules. It never
rewrites an invalid config, removes a lock, edits task or spec files, or touches
Git. Without `--fix`, `doctor` and `check` only read. Anything they cannot
repair stays as a finding and the command exits 1; `--json` returns `fixes` and
the remaining `findings`.

## Work states

A task moves `todo -> in_progress -> review -> done`, and can be `blocked` at any
point. Claiming is what creates ownership; `done` archives the file and releases
the lease. `depends_on` prevents a task from starting before its predecessor is
finished. The exact transitions are in `docs/task-flow.md`.

## Running more than one agent

- One task per session. Claim it before editing.
- Workers take work from `ai task ready` or `ai task next --agent <name>`; a
  task whose dependency is not done never appears there.
- Lock the paths you will touch. Paths and globs overlap, so `src/billing` and
  `src/billing/invoice.py` conflict.
- Acquire in a fixed order: task lease, file leases, then the git index.
- Review in a separate session; the producer does not sign off on its own work.
- Prefer `git worktree` for parallel implementation. It removes most contention;
  leases still apply inside each worktree.

`ai git begin/end` serializes the shared index, and `ai git verify --strict`
refuses to call a staged set safe when a path has no held lease. Details:
`docs/multi-agent.md` and `docs/orchestration.md`.

## When a context window ends

```sh
ai checkpoint 0007 --agent codex --percent 85 \
  --status "writer fails on empty rows" \
  --next "handle missing vat_id, add the empty-row test" \
  --files src/export/writer.py \
  --verification "npm test: 12 passed, 1 failing"

ai handoff 0007 --agent codex --reason "context limit"
ai resume 0007
```

A checkpoint is a structured snapshot: objective, current truth, done items,
exact stopping point, next steps, decisions, forbidden approaches, files and
verification. Its JSON sidecar records git state and file fingerprints, so
`resume` can show commits and files that changed since it was written. The
recovery rules are in `docs/recovery.md`.

## Keeping the repository clean

AI scratch output is quarantined:

```sh
ai artifact put scratch/ --reason "agent temp files"
ai artifact list
ai artifact clean --all
```

`ai check` fails when a watched path (`tmp/`, `scratch/`, ...) appears in the
project root. The watch list and the rest of the configuration live in
`config/workspace.json`.

## Tool wiring

Adapters do not restate rules; they point a tool at `.ai/AGENTS.md`.

| Tool           | Root file                                           |
| -------------- | --------------------------------------------------- |
| Claude Code    | `CLAUDE.md`                                         |
| Cursor         | `.cursor/rules/ai-workspace.mdc`                    |
| GitHub Copilot | `.github/copilot-instructions.md`                   |
| Codex          | `AGENTS.md`                                         |
| Other          | Paste `adapters/generic/README.md` into the session |

`ai adopt` generates the first four locally and adds them to `.gitignore`.
Manual instructions remain in `adapters/`.

## Chat-only assistants

A web chat or a model without repository access cannot read `.ai/`. Generate a
self-contained brief and paste it into that chat:

```sh
ai brief 0007                  # current task, spec, checkpoint, repo state, rules
ai brief 0007 --max-chars 12000
```

The brief tells the external model what it may not assume (for example, that it
ran tests) and asks it to return patches and commands for a human to execute.
It is read-only and never changes the workspace.

## Requirements

- Git, if you plan to clone and commit.
- Python 3.8+ for the CLI. The launchers discover `python3`, `python` or `py -3`.
- Nothing else: no packages, no build step, no background service.

## License

MIT. See `LICENSE`.
