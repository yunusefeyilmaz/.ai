# Artifact hygiene

The project outside `.ai/` is product territory. AI sessions produce a lot of
files that are not product code: scratch analyses, temporary scripts, logs,
downloaded references, generated notes. Those files are useful during a task and
harmful afterwards.

## The rule

> If an agent generates it and it is not product code, it lives under `.ai/`.

Allowed locations:

| Kind | Location |
|------|----------|
| Task bodies and notes | `tasks/active/<id>-<slug>.md` |
| Specs and plans | `specs/` |
| Decisions | `docs/decisions/` |
| Runtime state | `runtime/state/` |
| Logs | `runtime/logs/` |
| Scratch files, experiments, references | `runtime/artifacts/` |

Nothing else. No `notes.md` at the project root, no `tmp/`, no `scratch/`, no
`analysis-output.txt` beside the source.

## Quarantine

When a scratch file must live outside `.ai/` during a task (some tools only write
next to the source), move it into the quarantine when you are done:

```sh
ai artifact put tmp/ --reason "llm temp output"
ai artifact put analysis.json --agent implementer --reason "reference data"
```

`ai artifact put` moves the path into `runtime/artifacts/<timestamp>-<name>` and
records it in `runtime/artifacts/MANIFEST.json`. Inspect and purge with:

```sh
ai artifact list
ai artifact clean --all
```

Quarantined files are ignored by Git and never shipped.

## Enforcement

`config/workspace.json` lists watch paths:

```json
"artifacts": {
  "quarantine": "runtime/artifacts",
  "watch": ["tmp", "temp", "scratch", ".cache", "ai-notes", "notes-ai"]
}
```

`ai check` fails when any watch path appears at the project root. Add your own
conventions to the list — for example a `*-ai.md` pattern is usually better
handled by a team convention and a review check than by this built-in list.

## Evidence is not an artifact

Do not store raw command output as a committed file. Evidence is a pointer:

- the command (`ai check`),
- the result (exit code, counts, test names),
- the place a human can reproduce it.

Store the pointer in the task body. If you need a log for debugging, put it under
`runtime/logs/`; it is transient by design.

## Why this matters

- Reviewers can see the real diff instead of noise.
- Agents stop "helpfully" adding generated files to commits.
- A clean tree makes `git status` a signal again.
- The workspace can be deleted or re-cloned without losing product code.
