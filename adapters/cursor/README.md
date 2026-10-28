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
For every file-changing task in a Git repository, claim a task and start its
branch with `.ai/scripts/ai git start` before editing; run `git setup` if needed
and stop if branch creation fails. Read-only work and non-Git folders are
exempt. Follow `.ai/docs/git-workflow.md` and verify with `.ai/scripts/ai check`.
Keep all AI-generated files inside .ai/.
```

## Notes

- `alwaysApply: true` is the closest equivalent to auto-load.
- Cursor cannot enforce a read-only reviewer; run review in a fresh chat or a
  separate agent.
- Use the terminal for `ai` commands. On Windows, `.ai\scripts\ai.cmd`.

Do not duplicate the invariants here; the rule points at `AGENTS.md`.
