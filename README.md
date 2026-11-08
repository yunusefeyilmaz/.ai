<pre>
           _
    ____ _(_)
   / __ `/ /
 _/ /_/ / /
(_)__,_/_/
</pre>

A small, self-contained workspace that lets AI coding agents work on a project like
a professional team: a **chief** plans, **implementers** build, **reviewers**
approve. It adds one task ledger, file locks, standard Git handling and one
definition of "finished" — with no server, no database and no network access.

You give your AI one short request. The chief asks you how much process you want
(review? Git? tests?), splits the work into linked tasks, and the workers pick them
up. The `ai` command does the bookkeeping, so the agents spend their effort on the
code.

## 1. Install

You need [Rust](https://rustup.rs) (1.85 or newer) and `git`. Nothing else — no
package registry credentials, no Python, no service.

```sh
git clone https://github.com/yunusefeyilmaz/.ai.git .ai
cd .ai
cargo build --release
```

Then adopt and verify the workspace from your **project folder**:

**macOS / Linux**

```sh
.ai/target/release/ai adopt
.ai/target/release/ai doctor
```

**Windows (PowerShell)**

```powershell
.\.ai\target\release\ai.exe adopt
.\.ai\target\release\ai.exe doctor
```

`adopt` creates the small pointer files your AI tool reads (`AGENTS.md`,
`CLAUDE.md`, Cursor and Copilot rules). It adds those pointers, `.ai/runtime/`,
`.ai/worktrees/` and `.github/workflows/ai-check.yml` to `.gitignore`; the ledger
(`tasks/`, `specs/`, `config/`, `docs/`) stays committed. Run it once per clone.
`doctor` should end with `0 error(s)`.

### Launchers

`ai.cmd` (Windows) and `ai` (POSIX) find the release binary, then the debug
binary, then fall back to `cargo run`. On macOS/Linux mark the shell launcher
executable once:

```sh
chmod +x .ai/ai
```

| System             | Launcher                 | Shortcut                                                                         |
| ------------------ | ------------------------ | -------------------------------------------------------------------------------- |
| macOS / Linux      | `.ai/ai`                 | add `<project>/.ai` to `PATH`, or `alias ai=<project>/.ai/ai`                    |
| Windows PowerShell | `.\<project>\.ai\ai.cmd` | add `<project>\.ai` to `PATH`, or `Set-Alias ai <project>\.ai\ai.cmd` (absolute) |
| Windows cmd        | `.ai\ai.cmd`             | add `<project>\.ai` to `PATH`                                                    |

A PATH entry is more durable than a shell alias: aliases are session-scoped and
relative paths break after `cd`. In the examples below, `ai` means this launcher.

### First verified change (90 seconds)

```sh
.ai/ai start --agent implementer             # wire the workspace, claim the demo task
.ai/ai check --task 0001 --agent implementer # record evidence
```

`ai start` creates one task named "Try the workspace" so a fresh install has
something to claim. It is the single documented demo/task-creation exception to
"only the chief creates tasks"; use `--no-demo` to skip it. For real work, answer
`ai setup` and let the chief plan (section 2).

## 2. Give your AI a job

Open your AI tool in the project and paste **one** of these. The agent reads the
workspace rules itself.

**Start a new job (the chief plans it):**

```text
Read .ai/AGENTS.md. You are the chief. Do not write code. First run
`ai now --agent chief --role chief`, then ask me the setup questions it prints,
store my answers, split this job into linked tasks, and tell me when the workers
can start.

Job: <describe what you want built in a few sentences>
```

**Start a worker (once tasks exist; one session per worker):**

```text
Read .ai/AGENTS.md. You are an implementer named <name>. Run
`ai now --agent <name> --role implementer` and follow it. Deliver one task, then
stop and report; wait for my go-ahead before taking another.
```

**Start a reviewer (if you chose reviews):**

```text
Read .ai/AGENTS.md. You are a reviewer named <name>. Run
`ai now --agent <name> --role reviewer` and follow it. Review one task: approve and
merge it, or send it back with what is missing.
```

Use the launcher for your system from the table above (`.ai/ai` on macOS/Linux,
`.ai\ai.cmd` on Windows); the agent adapts the command to its shell.

## 3. What happens

```
 you ──job──> CHIEF ──asks──> you: review? git? tests? checks? how many workers?
                 │  (answers are saved in .ai/config/workspace.json)
                 └──plans──> tasks with dependencies, file locks and acceptance criteria
                                 │
        IMPLEMENTER  `ai task next`    claims a ready task: locks, branch (or worktree) are set up for it
                     ...writes code and tests...
                     `ai task review`  runs the project checks, delivers, stops and waits for you
                                 │
        REVIEWER     `ai task next --review`  takes the oldest delivery
                     `ai git finish` + `ai task done`   merges into develop, closes the task
                     or `ai task request-changes`        sends it back with a reason
```

- **Only the chief creates tasks**, and only after you answered the setup questions.
  Workers claim what exists.
- **After delivering, a worker stops** and waits for you (unless you allowed
  `continue` in the setup).
- **One worker or many.** With one worker, every task gets its own Git branch. With
  several (`workers` greater than 1) every task also gets its own checkout under
  `.ai/worktrees/`, so workers never step on each other. Worktrees are _not_
  required for a single worker.
- **Git is your choice.** If you say no to Git in the setup, the Git steps are
  skipped. If yes, the agent sets up Gitflow (`ai git setup --yes` for an agent with
  no terminal; it lists the files and refuses anything that looks like a secret).
- If a session ends midway, the next agent continues from `ai resume <task>`.

## 4. Commands you will actually use

| You want to                   | Run                                                                              |
| ----------------------------- | -------------------------------------------------------------------------------- |
| see what is going on          | `ai status --board` or `ai context`                                              |
| see why a task is where it is | `ai history <task>`                                                              |
| change a workflow answer      | `ai setup --set review=no` (keys: review, checks, git, tests, continue, workers) |
| add your test command         | `ai setup --check "tests=cargo test"`                                            |
| fix a broken workspace        | `ai doctor --fix`                                                                |
| clean up finished worktrees   | `ai worktree prune`                                                              |

The full list is in `GUIDE.md`. Rules for agents are in `AGENTS.md`. The
machine-readable contract is `ai capabilities --json`.

## The guarantees

- **A durable task ledger.** Every piece of work is a Markdown file with an id,
  owner, status and a log of who moved it and why. It survives the session that
  created it.
- **Ownership with leases.** A task claim and any file lock are JSON leases with a
  TTL. A live lease is a refusal; an expired one can be reclaimed.
- **Verification as evidence.** `ai check --task <id> --agent <n>` records what ran
  and its exit codes against the commit; review requires it when you asked for
  checks.
- **A reviewer who is not the author — when you chose review.** `done` needs a
  different agent than the one that delivered unless you answered `review=no` in
  `ai setup`. A solo worker with review on must start a reviewer session.
- **A place for operational state.** Checkpoints, locks and scratch artifacts live
  under `.ai/runtime/` and never enter the product tree.

## How the pieces fit

```
your-project/
├── <product code>
└── .ai/
    ├── Cargo.toml       Rust package: one binary, `ai`
    ├── src/
    │   ├── main.rs      CLI parser + dispatch
    │   ├── lib.rs       library surface (so tests and tools can embed it)
    │   ├── cli.rs       every command, argument and flag (clap)
    │   └── core/ config/ tasks/ specs/ runtime/ git/ decisions/ ui/ cmd/
    ├── ai, ai.cmd       launchers (release → debug → cargo run)
    ├── AGENTS.md        entry contract for every agent
    ├── GUIDE.md         operator's handbook
    ├── config/          mode, TTLs, budgets, workflow rules, project checks
    ├── tasks/           task ledger: active/, done/, generated BOARD.md
    ├── specs/           acceptance criteria per behavior change
    ├── runtime/         leases, checkpoints, handoffs, artifacts, logs
    ├── templates/git/   commit and PR templates
    ├── docs/            architecture, blueprint, flow, concurrency, recovery, decisions/
    ├── agents/          role cards
    ├── prompts/         reusable prompt bodies
    ├── adapters/        per-tool pointers
    ├── skills/          optional extensions
    └── tests/           end-to-end CLI tests (cargo test)
```

The split matters: `.ai/` is agent territory, the rest is product territory.
`ai adopt` is the explicit operator action that creates local pointers and the
narrow ignore rules (`.ai/runtime/`, `.ai/worktrees/`); the workspace ledger stays
in version control.

### Building and testing

```sh
cargo build --release     # the binary at target/release/ai (ai.exe on Windows)
cargo test                # unit tests + end-to-end CLI tests
cargo clippy --all-targets -- -D warnings
cargo fmt --all --check
```

Each integration test builds a throwaway workspace under the OS temp directory, so
`cargo test` never touches this checkout. The suite is identical on Windows, macOS
and Linux; CI runs all three plus a 1.85 MSRV check.

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

`todo -> in_progress -> review -> done`. A reviewer can send a task in review back
(`changes_requested`, then the producer reclaims it), and any task can be `blocked`.
Claiming creates ownership; `done` (by a different agent than the producer)
archives the task and its spec and frees every lock. `depends_on` keeps a task from
starting before its predecessor is finished. The exact transitions are in
`docs/task-flow.md`.

Who may approve is set by `workflow.playbook`: `solo` (one agent designs,
implements and reviews), `pair` (a second agent), or `team` (workers plus
reviewers/QA). Before planning, the chief proposes the architecture and the user
approves or changes it: `ai blueprint propose` -> `ai blueprint approve`. See
`docs/blueprint.md`.

## Running more than one agent

- One task per session. Claim it before editing.
- Workers take work from `ai task ready` or `ai task next --agent <name>`; a
  task whose dependency is not done never appears there.
- Lock the paths you will touch. Paths and globs overlap, so `src/billing` and
  `src/billing/invoice.rs` conflict.
- Acquire in a fixed order: task lease, file leases, then the git index.
- Review in a separate session; the producer does not sign off on its own work.
- Parallel workers get one `git worktree` each, created by `ai task claim`
  (`ai setup --set workers=N`); leases still apply inside each worktree.

`ai git begin/end` serializes the shared index, and `ai git verify --strict`
refuses to call a staged set safe when a path has no held lease. Details:
`docs/multi-agent.md` and `docs/orchestration.md`.

## When a context window ends

```sh
# one line works in every shell (PowerShell, cmd, bash, zsh)
ai checkpoint 0007 --agent codex --percent 85 --status "writer fails on empty rows" --next "handle missing vat_id, add the empty-row test" --files src/export/writer.rs --verification "cargo test: 12 passed, 1 failing"

ai handoff 0007 --agent codex --reason "context limit"
ai resume 0007
```

PowerShell uses a backtick (`` ` ``) for line continuation, not `\`; when in doubt,
keep the command on one line as above.

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

| Need       | Why                                                                     |
| ---------- | ----------------------------------------------------------------------- |
| Rust 1.85+ | Building the binary (`cargo build --release`).                          |
| Git        | Cloning, and every Gitflow command. Read-only commands work without it. |
| A terminal | Only `ai reset --hard` and `ai task discard` require one.               |

No runtime dependency: after `cargo build --release`, `target/release/ai` is a
single self-contained executable you can copy anywhere.

## Platform support

Windows, macOS and Linux, all tested by CI. The binary uses no platform-specific
crates; project checks run through `cmd /C` on Windows and `sh -c` elsewhere, and
lock files use `LockFileEx`/`flock` through `fs2`.

## License

MIT. See `LICENSE`.
