# Bootstrap

Fill in the project-specific parts of the workspace. Run this once, in a fresh
session, before the first task. The workspace is already functional; bootstrap
only makes it *yours*.

## Ask first, then write

1. **Languages.** Interview language and document language. Record both in
   `config/workspace.json` under `language`. The protocol stays English.
2. **Mode.** `lite` (solo, low risk) or `strict` (team, critical). Record it in
   `config/workspace.json`.
3. **Product.** What is this project? Who uses it? Fill the Intent section of
   `docs/architecture.md` if it is still generic.
4. **Stack and commands.** How is it built, tested and linted? Put the canonical
   commands in `config/workspace.json` under `checks`:

```json
"checks": [
  { "name": "tests", "command": "npm test", "fast": true },
  { "name": "lint", "command": "npm run lint", "fast": true },
  { "name": "build", "command": "npm run build", "fast": false }
]
```

5. **Boundaries.** Which paths are shared between agents? Name the locks you will
   use (`src/billing`, `package.json`, `db/migrations`).
6. **Artifact watch list.** Add project-local scratch names to
   `artifacts.watch`.

## Do not

- Do not invent project facts. Ask.
- Do not copy the whole architecture into `AGENTS.md`; keep it a signpost.
- Do not add checks you cannot run in CI.

## Finish

```sh
ai doctor
ai check
```

If this project is a Git repository, run `ai git setup` once in this clone
before starting its first file-changing task. Each task then starts its own
branch with `ai git start` after claim and before editing; see
`docs/git-workflow.md`.

Then tell the human: the mode, the verification command, and how to start the
first task.
