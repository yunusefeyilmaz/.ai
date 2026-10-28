# GitHub Copilot adapter

## Wire

Create `.github/copilot-instructions.md` at the project root:

```md
# Copilot instructions

This project uses the .ai engineering workspace.
Read `.ai/AGENTS.md` and `.ai/docs/git-workflow.md` first. For every
file-changing task in a Git repository, claim a task and successfully run
`.ai/scripts/ai git start` before editing; run `git setup` if needed and stop if
branch creation fails. Read-only tasks and non-Git folders are exempt.
Follow `.ai/docs/task-flow.md`; verify with `.ai/scripts/ai check`.
All AI-generated files belong inside `.ai/`.
```

For path-specific rules, add `.github/instructions/*.instructions.md` files that
point back to `.ai/docs/` rather than restating them.

## Notes

- Copilot has no native subagent isolation; use a fresh chat for review.
- CI is the enforcement point: run `ai doctor --strict` and `ai check` on pull
  requests.
