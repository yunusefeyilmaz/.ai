# Generic adapter

For any agent that can read files and run shell commands.

## Wire

Give the agent this at the start of a session:

```
This project uses the .ai engineering workspace.
Read .ai/AGENTS.md before doing anything.
Follow .ai/docs/task-flow.md.
Claim a task with .ai/scripts/ai task claim <id> --agent <name> before editing.
Verify with .ai/scripts/ai check. Do not claim "done" without its output.
Keep all AI-generated files inside .ai/.
```

On Windows use `.ai\scripts\ai.cmd` instead of `.ai/scripts/ai`.

## If the CLI is unavailable

The protocol is plain files. You can:

- create and edit task files by hand using `tasks/TEMPLATE.md`;
- create lock files under `runtime/locks/` using the JSON format in
  `docs/multi-agent.md`;
- move scratch files to `runtime/artifacts/`;
- run the verification commands listed in `config/workspace.json`.

Never invent a shortcut that bypasses ownership or verification.
