# skills

Optional extensions. In the Rust port a skill is **data**, not code: prompt
bodies, templates and reference material that an agent loads when the skill's
`README.md` says it applies. Nothing here is required by the core, and the CLI
never executes anything from this folder.

A skill is a folder:

```
skills/<name>/
├── README.md       what it does and when an agent should use it
└── ...             prompts, templates, data the skill owns
```

Rules: depend downward only (the skill may reference `tasks/`, `specs/`,
`docs/`, `prompts/`); never edit the core's state files directly — use the `ai`
commands; keep output short (agents pay per token).

The Rust binary has one fixed command surface (see `ai capabilities --json`), so a
skill that needs new behaviour is a change to `src/cmd/` plus a test in
`tests/`, not a drop-in folder.
