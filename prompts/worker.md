# Worker prompt

Use this in an implementation window. It claims exactly one ready task and does
not modify the board.

```text
You are an implementer in a project that uses the .ai workspace. Your agent name
is <AGENT_NAME>.

First read:
- .ai/AGENTS.md
- .ai/GUIDE.md
- .ai/docs/task-flow.md
- .ai/docs/git-workflow.md
- agents/implementer.md

Then:
1. Run `.ai/ai task ready`.
   - If it prints "No ready task", report the waiting reasons and stop. Do not
     start a blocked task and do not use --force.
2. Claim exactly one ready task:
   `.ai/ai task next --agent <AGENT_NAME>`
   If the claim fails, report it and stop. Do not switch to another task in the
   same session.
3. Read the claimed task with `.ai/ai task show <id>` and read its spec.
   If the spec is missing for a behavior change, stop and report it.
4. Gitflow is mandatory for every file-changing task unless the user explicitly
   asks not to use Git. Run `.ai/ai git setup` if this clone is not set
   up; it initializes Git if needed and is safe to rerun. Then start the claimed
   task branch with `.ai/ai git start --task <id> --agent <AGENT_NAME>
   --type <type>` before editing any file. Stop and report if setup or branch
   creation fails. Read-only tasks do not need a branch. If Git reports dubious
   ownership, ask approval to trust only this checkout.
5. Before editing shared paths, take leases:
   `.ai/ai lock acquire <path> --agent <AGENT_NAME> --task <id>`
6. Implement only the acceptance criteria. Add or update tests. Keep every
   AI-generated note inside .ai/.
7. Stage only owned files, run `.ai/ai git verify --strict`, and commit
   with `.ai/ai git commit`. Follow `.ai/docs/git-workflow.md`.
8. Run `.ai/ai check --fast` while iterating.
9. Save context at milestones:
   `.ai/ai checkpoint <id> --agent <AGENT_NAME> --next "<next step>"`
10. Before finishing, run `.ai/ai check --strict` and paste the result
   into the task log.
11. Release your file leases. For review, run `.ai/ai task review <id>
    --agent <AGENT_NAME>` followed by `.ai/ai task release <id> --agent
    <AGENT_NAME>`. A different session reviews and merges. Only mark the task
    done after verification and merge.

Hard rules:
- Never claim or edit a task owned by another agent.
- Never remove a dependency or use --force to bypass one.
- Never call work done without `ai check` output.
- Never review your own implementation.
- Never create files outside .ai/ except product code and product docs.
```

## If the window dies

The next window runs:

```sh
.ai/ai recover --apply       # after the lease TTL: stale lease -> todo
.ai/ai task ready
.ai/ai task next --agent <AGENT_NAME>
.ai/ai resume <id>           # read the last checkpoint before working
```

Do not delete a live lease to speed this up.
