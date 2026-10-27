# Agents

Role cards bind responsibility to a session, not to a technology. Any capable
model can take any role; what matters is that the producer and the verifier are
never the same session.

| Role | Card | Owns |
|------|------|------|
| Orchestrator | `orchestrator.md` | Entry, triage, handoffs, gates |
| Planner | `planner.md` | Spec and plan |
| Implementer | `implementer.md` | Code and `ai check --fast` |
| Reviewer | `reviewer.md` | Independent review |
| QA | `qa.md` | Acceptance criteria and evidence |

## Rules for every role

1. Read `../AGENTS.md` first.
2. Claim a task before working; one task per session.
3. Acquire locks for shared resources before editing.
4. Do not edit another agent's task or a locked resource.
5. End by leaving the task and its log in a state the next role can pick up.
6. Never claim "done" without `ai check` output.

## Picking a role

- Solo agent: use `orchestrator.md` and switch hats explicitly. Still run review
  in a fresh session.
- Multiple agents: one role per session. In `strict` mode this is required.

## Agent names

Use stable names in locks and task owners: `planner`, `implementer-1`,
`reviewer-a`, `qa`. The name identifies the session, not the model, so a handoff
is visible in the task log.
