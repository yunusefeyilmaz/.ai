# Architecture

`.ai` is a folder, not a framework. It has no runtime service, no database and
no code generation. Everything is files: Markdown for humans and agents, JSON for
configuration, and a single Rust binary for the operations that need to be atomic.

## Layers

```
project/                  <- product territory (the real repo)
└── .ai/                  <- AI territory (this workspace)
    ├── Cargo.toml        the `ai` binary (edition 2021, MSRV 1.85)
    ├── src/              main.rs dispatches; cli.rs defines every flag; then
    │                     core, config, tasks, specs, runtime, git, decisions,
    │                     ui and cmd (one file per command) — one folder per domain
    ├── ai, ai.cmd        launchers: release binary, debug binary, `cargo run`
    ├── AGENTS.md         signpost: session loop, required order, invariants
    ├── GUIDE.md          practical manual: install, loop, prompts, recovery
    ├── tests/            end-to-end CLI tests (`cargo test`)
    ├── config/           one JSON file: mode, languages, ttl, workflow, checks
    ├── tasks/            local task store: active/, done/, BOARD.md
    ├── specs/            one spec per behavior change
    ├── runtime/          locks/, state/, artifacts/, logs/ (never committed)
    ├── templates/git/    commit and PR templates
    ├── docs/             durable memory: architecture, blueprint, flow, locks,
    │                     orchestration, recovery, hygiene, decisions/
    ├── agents/           role cards (responsibility, not technology)
    ├── prompts/          reusable prompt bodies
    ├── adapters/         per-tool pointers (never duplicate rules)
    └── skills/           optional extensions (prompts and templates)
```

The boundary is the point: anything an agent generates that is not product code
stays inside `.ai/`. The project never accumulates `notes.md`, `tmp/` or
`analysis-*.txt` from AI sessions.

## What actually changes agent behavior

Instructions in prose are weak. Three mechanisms carry the design:

1. **Auto-loaded context.** Tools read root `AGENTS.md` at startup. It stays
   short and points at the rest; anything not linked from it may never be seen.
2. **A cheap gate.** `ai check` must be fast enough to run often. Expensive
   verification gets skipped and replaced by confident claims.
3. **Refusals that do not depend on memory.** Lease creation is atomic, live
   leases are rejected, and CI runs the same gate. (In `lite` mode `ai check` is not
   forced before review unless you chose `checks` in `ai setup`; `ai git finish` and CI
   always run it.) These survive a new session.

## Ceremony levels

- **lite** — solo work and low-risk changes. The artifacts exist; they rarely
  block. Choose it when a single agent may run the whole loop quickly.
- **strict** — teams and critical systems. Spec, plan and triage need a human
  decision; roles do not share a session.

The level is `mode` in `config/workspace.json`. It changes gates, not file
formats, so switching later requires no migration.

## How agents share the workspace

```
agent A                    filesystem                    agent B
   |                           |                            |
   |-- ai task claim 0001 ---->| create lock (O_EXCL)       |
   |<-- ok --------------------|                            |
   |                           |<-- ai task claim 0001 -----|
   |                           |--- lock exists ----------->| refused
   |-- edit files (task lock)--|                            |
   |-- ai check -------------->|                            |
   |-- ai task done 0001 ----->| needs review + 2nd agent   |
```

There is no server and no clock to trust. Locks are advisory and expire; the
details are in `docs/multi-agent.md`.

## Why this shape

The design is driven by four pressure points rather than by a methodology:

1. **Sessions are short; projects are not.** A task file, a spec and a
   checkpoint let the next session continue instead of starting over.
2. **Parallel sessions collide.** Task claims and path leases with overlap
   detection make ownership explicit; a live lease is a refusal.
3. **Agents generate clutter.** A quarantine boundary enforced by `ai check`
   keeps the product tree readable.
4. **Verification is the only shared truth.** One command used by humans, agents
   and CI is cheaper to trust than a status field.

Everything else — roles, prompts, modes — is optional structure around those
four.

## Design principles

- **Files over chat.** Sessions forget; files do not.
- **One contract.** Humans, agents, hooks and CI all run `ai check`.
- **Evidence over claims.** Attach the command and result to the task.
- **Small signpost.** A long `AGENTS.md` gets ignored in the middle; keep it short.
- **Boring runtime.** One Rust binary, atomic file operations, no daemon, no
  network, no garbage collector.
- **Escape hatches.** Any runtime that can read and write files can follow the
  protocol when the CLI is unavailable.
