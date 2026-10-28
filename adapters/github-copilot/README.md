# GitHub Copilot adapter

## Wire

Create `.github/copilot-instructions.md` at the project root:

```md
# Copilot instructions

This project uses the .ai engineering workspace.
Read `.ai/AGENTS.md` and `.ai/docs/git-workflow.md` first. For every
file-changing task, run `.ai/scripts/ai git setup` if needed (it initializes
Git if absent), claim the task and successfully run `.ai/scripts/ai git start`
before editing. Stop if setup or branch creation fails. Read-only tasks need no
branch. Ask approval if Git reports dubious ownership.
Follow `.ai/docs/task-flow.md`; verify with `.ai/scripts/ai check`.
All AI-generated files belong inside `.ai/`.
```

For path-specific rules, add `.github/instructions/*.instructions.md` files that
point back to `.ai/docs/` rather than restating them.

## Notes

- Copilot has no native subagent isolation; use a fresh chat for review.
- CI is the enforcement point: run `ai doctor --strict` and `ai check` on pull
  requests.
