# Claude Code adapter

## Wire

Create `CLAUDE.md` at the project root:

```md
# CLAUDE.md

This project uses the .ai engineering workspace.

Read `.ai/AGENTS.md` first. It is the only signpost you need.
For every file-changing task, run `.ai/ai git setup` if needed; it
initializes Git when absent. Claim the task and successfully start its branch
with `.ai/ai git start` before editing. Stop if setup or branch creation
fails. Read-only tasks need no branch. If Git reports dubious ownership, ask
approval to trust only this checkout. Follow `.ai/docs/git-workflow.md` and
`.ai/docs/task-flow.md`.
Verification: `.ai/ai check`.

Never create AI notes or scratch files outside `.ai/`.
```

If `.ai/` is the project root (template install), `AGENTS.md` is already read
natively and no `CLAUDE.md` is needed.

## Recommended permissions

Deny destructive Git operations in the project's settings:

```json
{
  "permissions": {
    "deny": ["Bash(git push --force*)", "Bash(git reset --hard*)"]
  }
}
```

## What maps well

- Subagents are a natural fit for the reviewer role (no edit tools).
- Hooks can enforce "shipped specs are immutable" if you need it.
- Slash commands can wrap `ai task new`, `ai task claim` and `ai check`.

Keep `CLAUDE.md` short; it is a pointer, not a copy of the rules.
