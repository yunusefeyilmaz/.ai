# Cursor adapter

## Wire

Create `.cursor/rules/ai-workspace.mdc` at the project root:

```mdc
---
description: AI workspace entry rules
alwaysApply: true
---

This project uses the .ai engineering workspace.
Read .ai/AGENTS.md first, then .ai/docs/task-flow.md.
Claim a task before editing; verify with .ai/scripts/ai check.
Keep all AI-generated files inside .ai/.
```

## Notes

- `alwaysApply: true` is the closest equivalent to auto-load.
- Cursor cannot enforce a read-only reviewer; run review in a fresh chat or a
  separate agent.
- Use the terminal for `ai` commands. On Windows, `.ai\scripts\ai.cmd`.

Do not duplicate the invariants here; the rule points at `AGENTS.md`.
