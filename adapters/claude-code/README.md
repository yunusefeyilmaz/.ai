# Claude Code adapter

## Wire

Create `CLAUDE.md` at the project root:

```md
# CLAUDE.md

This project uses the .ai engineering workspace.

Read `.ai/AGENTS.md` first. It is the only signpost you need.
For every file-changing task in a Git repository, claim the task and
successfully start its branch with `.ai/scripts/ai git start` before editing.
Run `git setup` if needed and stop if branch creation fails. Read-only tasks and
non-Git folders are exempt. Follow `.ai/docs/git-workflow.md` and
`.ai/docs/task-flow.md`.
Verification: `.ai/scripts/ai check`.

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
