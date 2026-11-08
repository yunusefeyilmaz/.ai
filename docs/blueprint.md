# Blueprint: the AI proposes, the user approves

A new project should not begin with the AI guessing a stack, and it should not be
limited to the stacks this CLI happens to know. The chief (the AI) analyzes the
request and the machine, writes a proposal, and the user confirms or changes it
**before** a single task is planned.

There is deliberately **no language or framework registry in the binary**. The
CLI proves mechanical facts; the AI decides languages, architecture, folders,
naming, checks and conventions, including ones nobody anticipated. The approved
document is stored verbatim, so a project in Zig, Gleam, Odin, a private DSL or a
mix of several stacks works exactly like one in Rust.

## The loop

```sh
ai setup --set review=yes checks=yes git=yes tests=yes mode=lite playbook=pair

# 1. Facts (no guessing): OS, arch, shell, Git, top-level tree, toolchains
ai blueprint propose

# 2. The chief authors the proposal from those facts + the user's request
ai blueprint propose --from analysis.json     # or --from - for stdin

# 3. The user reviews it
ai blueprint show

# 4. The user changes anything they disagree with
ai blueprint revise --set naming.files=PascalCase
ai blueprint revise --set languages='["Rust","Python"]'
ai blueprint revise --set conventions.release=trunk

# 5. The user approves; values are applied to config/workspace.json
ai blueprint approve --agent <user>

# 6. Planning (strict mode asks for the plan approval too)
ai plan apply plan.json --role chief --dry-run
ai plan apply plan.json --role chief --approved-by <user>
```

A bare `ai blueprint propose` writes a **draft**: facts plus empty slots and the
questions to answer. It cannot be approved — the chief has to do the analysis
first. Re-running `propose` while pending regenerates the draft/proposal; it
refuses to overwrite an **approved** blueprint (approve a revision instead).

## What the facts contain (mechanical only)

Nothing leaves the machine. The scan reports only what it can observe:

| Field | Example |
|-------|---------|
| `os`, `arch`, `shell`, `pathSeparator` | `windows`, `x86_64`, `cmd`, `\` |
| `git.repository`, `git.branch`, `git.tracked` | repository state, file count, first 120 tracked paths |
| `topLevel` | every top-level entry (files and `dir/`), capped at 200 |
| `tooling` | binaries that answered `--version`, capped at 3 s each |

`tooling` is a **hint list**, not support. It is extensible from config:

```json
{ "blueprint": { "probes": ["zig", "gleam", "roc"] } }
```

## What the chief writes (`analysis.json`)

Any JSON object is accepted. The keys the CLI enforces today are below; every
other key is preserved under `config.blueprint.approved` for agents and future
versions.

```json
{
  "languages": ["Zig", { "name": "Gleam", "why": "worker services" }],
  "architecture": "hexagonal: domain inside, adapters outside",
  "layout": ["src/domain/", "src/adapters/", "tests/"],
  "naming": { "files": "snake_case", "functions": "snake_case", "types": "PascalCase" },
  "testing": { "framework": "zig build test", "location": "tests/" },
  "checks": [{ "name": "unit", "command": "zig build test", "timeoutSeconds": 300 }],
  "guidelines": ["one behavior per task", "no new dependency without approval"],
  "conventions": { "release": "trunk", "comments": "explain why" },
  "workflow": { "mode": "strict", "playbook": "solo", "workers": 2 },
  "git": { "integrationBranch": "main", "productionBranch": "release", "isolation": "worktree" }
}
```

Validation is structural, never a whitelist of technologies:

- `languages` is an array of names or `{"name": ...}` objects — **any** name;
- `layout`, `guidelines`, `checks` are arrays; each check needs a `command`;
- `naming`, `testing`, `workflow`, `git`, `conventions` are objects;
- `workflow.mode` ∈ `lite|strict`, `workflow.playbook` ∈ `solo|pair|team`, and
  `workflow.workers` is 1–32 — these three are product behaviour, not project
  technology, so they stay closed;
- everything else is free-form.

## What approval applies

| Proposal key | Lands in `config/workspace.json` |
|--------------|----------------------------------|
| `workflow.mode` | `mode` |
| `workflow.playbook` | `workflow.playbook` |
| `workflow.workers` | `orchestration.maxParallel` (and `git.isolation` if unset) |
| other `workflow.*` | `workflow.*` (e.g. `requireReview`, `requirePlanApproval`) |
| `git.*` | `git.*` |
| `checks` | `checks`, only when the project has none configured yet |
| `languages`, `architecture`, `layout`, `naming`, `testing`, `guidelines`, `conventions`, `standards` | same top-level key |
| the whole proposal | `blueprint.approved` (never dropped) |

`ai blueprint approve` never replaces a corrupt `config/workspace.json` with a
default; it refuses and tells you to repair it.

## Gates

- An approved blueprint is required before planning: while it is **missing** or
  **pending**, `ai plan apply` and `ai task new --role chief` refuse and point at
  `ai blueprint propose` / `ai blueprint show`.
- In `strict` mode, or when `workflow.requirePlanApproval` is true, the plan also
  needs the user's approval: `--dry-run`, then `--approved-by <user>`. The
  approval is recorded in `runtime/state/plan-approval.json`.
- `ai doctor` warns while a proposal is pending, and when
  `config.blueprint.required` is true but no proposal exists.
- `ai now --role chief` recommends `ai blueprint propose` (missing) or
  `ai blueprint show` (pending) before `ai plan apply`.
- `ai brief` inlines the approved conventions so an external model does not need
  to read the repository.

## Token discipline

The blueprint is the first token-saving device: conventions are decided once and
read from one file. The rest of the loop is built the same way:

- `ai now` prints at most a handful of lines and the **one** next command;
- `ai now --json` is the compact machine contract (no task bodies);
- `ai brief --max-chars N` keeps the head (rules) and tail (commands) and cuts
  the middle;
- `ai review <id> --stat` shows the diff summary, not every line;
- agents should read the task, its spec and the files it must edit — not the
  whole repository or all docs.

## Playbooks

| Playbook | Who designs | Who implements | Who reviews |
|----------|-------------|----------------|-------------|
| `solo` | one agent | the same agent | the same agent (evidence still required) |
| `pair` | chief or user | one worker | a different agent |
| `team` | chief | several workers | reviewers / QA |

`lite` and `strict` are orthogonal: they decide how much process runs, while the
playbook decides who is allowed to approve. A user who wants no review at all
still answers `review=no`; the `solo` playbook keeps the review step and its
evidence.
