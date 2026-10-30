# Generic adapter

For any agent that can read files and run shell commands.

## Wire

Give the agent this at the start of a session:

```
This project uses the .ai engineering workspace.
Read .ai/AGENTS.md and .ai/docs/git-workflow.md before doing anything.
For every file-changing task, run .ai/ai git setup if needed (it
initializes Git if absent), claim the task and start its branch with
.ai/ai git start before editing. Stop if setup or branch creation fails.
Read-only work needs no branch. Ask approval if Git reports dubious ownership.
Follow .ai/docs/task-flow.md.
Verify with .ai/ai check. Do not claim "done" without its output.
Keep all AI-generated files inside .ai/.
```

On Windows use `.ai\ai.cmd` instead of `.ai/ai`.

## If the CLI is unavailable

The protocol is plain files. You can:

- create and edit task files by hand using `tasks/TEMPLATE.md`;
- create lock files under `runtime/locks/` using the JSON format in
  `docs/multi-agent.md`;
- move scratch files to `runtime/artifacts/`;
- run the verification commands listed in `config/workspace.json`.

Never invent a shortcut that bypasses ownership or verification.
