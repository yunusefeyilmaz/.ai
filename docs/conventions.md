# Conventions

Keep these stable so the CLI, the agents and CI agree.

## Language

- The workspace itself (rules, docs, CLI output, protocol fields) is **English**.
- Project documents may use another language. `config/workspace.json` records it
  under `language.documents` and `language.interviews`.
- Protocol values stay English: `todo`, `in_progress`, `review`, `blocked`,
  `done`, `lite`, `strict`, `null`.

## Identifiers

- Task ids are zero-padded, never reused: `0001`, `0002`, ...
- Task files are `tasks/active/<id>-<slug>.md`, e.g. `0001-add-invoice-export.md`.
- Specs are `specs/active/<id>-<slug>.md` when linked to a task, or a descriptive
  slug for exploratory work.
- Decision records are `docs/decisions/NNNN-<slug>.md`.
- Lock resources are lowercase path-like names: `src/billing`, `package.json`,
  `task-0001`.

## Front matter

Every task has: `id`, `title`, `status`, `owner`, `priority`, `spec`, `created`,
`updated`, `lock`. Use `null`, not an empty string. Timestamps are UTC ISO 8601
with a trailing `Z`.

## Task body

```md
# <id> - <title>

## Intent        <- the problem, not the solution
## Acceptance criteria   <- checkbox list, each independently testable
## Plan          <- ordered steps, links to the spec
## Notes         <- decisions, links, open questions
## Log           <- append-only; the CLI writes claims/releases here
```

## Specs

Required sections: Intent, Behavior, Acceptance criteria, Out of scope, Status.
Acceptance criteria must be observable from outside the implementation. A spec
with no way to fail is not a spec.

## Git

- One task per branch is a good default. The branch name references the task:
  `task/0001-add-invoice-export`.
- Commit messages describe the change, not the agent:
  `Add invoice CSV export`, not `AI changes`.
- Do not force-push shared branches, do not rewrite published history.
- `ai check` must be green before a commit that claims completion.
- Never commit `runtime/` state, raw evidence dumps or secrets.

## Commands

- Verification is `ai check`. There is no second contract.
- `ai check --fast` is for the inner loop and is not evidence.
- The full `ai check` result is what you attach to a task.
- CI runs `ai doctor --strict` and `ai check`.

## File hygiene

- No AI scratch files outside `.ai/`; use `ai artifact put`.
- Do not hand-edit `tasks/BOARD.md`; it is generated.
- Do not edit a file covered by another agent's live lock.
- Do not edit a task you do not own.

## Review

- The reviewer sees the diff, the spec and the check output, not the author's
  reasoning.
- Findings are classified: `blocker`, `should-fix`, `nit`.
- A human triages findings in strict mode; in lite mode the author may fix
  blockers directly and must record the decision in the task.
