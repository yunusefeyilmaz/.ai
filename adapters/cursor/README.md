# Cursor adapter

## Wire

Create `.cursor/rules/ai-workspace.mdc` at the project root:

```mdc
---
description: AI workspace entry rules
alwaysApply: true
---

This project uses the .ai engineering workspace.
Read .ai/AGENTS.md, .ai/docs/task-flow.md and .ai/docs/git-workflow.md first.
For every file-changing task, run `git setup` if needed (it initializes Git if
absent), claim the task and start its branch with `.ai/scripts/ai git start`
before editing. Stop if setup or branch creation fails. Read-only work needs no
branch. Ask approval if Git reports dubious ownership. Follow the workflow and
verify with `.ai/scripts/ai check`.
Keep all AI-generated files inside .ai/.
```

## Notes

- `alwaysApply: true` is the closest equivalent to auto-load.
- Cursor cannot enforce a read-only reviewer; run review in a fresh chat or a
  separate agent.
- Use the terminal for `ai` commands. On Windows, `.ai\scripts\ai.cmd`.

Do not duplicate the invariants here; the rule points at `AGENTS.md`.
