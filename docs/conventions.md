# Conventions

Keep these stable so the CLI, the agents and CI agree.

## Language

- The workspace itself (rules, docs, CLI output, protocol fields) is **English**.
- Project documents may use another language. `config/workspace.json` records it
  under `language.documents` and `language.interviews`.
- Protocol values stay English: `todo`, `in_progress`, `review`,
  `changes_requested`, `blocked`, `done`, `lite`, `strict`, `solo`, `pair`,
  `team`, `null`.
- Project naming is a decision, not a habit: the approved `config/blueprint.json`
  records `files`, `functions`, `types`, `json`, `branches`, `commits` and `env`
  naming under `naming`. New code follows it; changing it is a deliberate
  `ai blueprint revise` + `ai blueprint approve`, not a per-task choice.

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
`updated`, `lock`. The CLI also writes `depends_on`, `scope_allowed`,
`scope_forbidden`, `locks`, `branch`, `worktree`, `submitted_by`, `reviewed_by`,
`merged_into`, `merged_at` and `blocked_from` when they apply. That list is the
canonical schema: `tasks/TEMPLATE.md` and this section must agree. Use `null`,
not an empty string. Timestamps are UTC ISO 8601 with a trailing `Z`.

## Task body

```md
# <id> - <title>

## Intent        <- the problem, not the solution
## Acceptance criteria   <- checkbox list, each independently testable
## Plan          <- ordered steps, links to the spec
## Notes         <- decisions, links, open questions
## Log           <- append-only; the CLI writes claims/releases here
```

## Task front matter

The canonical field table. `tasks/TEMPLATE.md` starts from it, and `ai task
new` / the commands in the last column own the values.

| Field | Written by | Meaning |
|-------|-----------|---------|
| `id` | `ai task new` | Four-digit task id; the only id form the CLI accepts. |
| `title` | `ai task new` | Imperative one-liner. |
| `status` | state transitions | `todo`, `in_progress`, `review`, `changes_requested`, `blocked`, `done`. |
| `owner` | claim/release/review/done | Agent currently holding the task; `null` when free. |
| `priority` | `ai task new` | `low`, `medium`, `high`. |
| `spec` | `ai task new` / `--spec` | Path of the linked spec; the claim gate reads it. |
| `depends_on` | `ai task new` / `plan apply` | Comma-separated ids that must be `done` first. |
| `scope_allowed` | `--allow` | Globs the task may touch. |
| `scope_forbidden` | `--forbid` | Globs the task must not touch. |
| `locks` | `--lock` (default: `scope_allowed`) | File leases taken automatically at claim. |
| `branch` | `ai git start` | Task branch while Git is on. |
| `worktree` | claim/`git start` | Isolated checkout when `git.isolation = worktree`. |
| `submitted_by` | `ai task review` | Producer; a different agent must review. |
| `reviewed_by` | `ai task done` | Reviewer/approver. |
| `changes_requested_by` | `ai task request-changes` | Who sent it back. |
| `reviewed_at` | `ai task done` | When it was approved. |
| `merged_into` / `merged_at` | `ai git finish` | Integration branch and merge time. |
| `blocked_from` | `ai task block` | Status restored by `unblock`. |
| `github_issue` / `github_pr` | `ai task link` | External references. |
| `created` / `updated` | CLI | ISO timestamps. |
| `lock` | claim/release | The `task-<id>` lease while claimed. |
| `demo` | `ai start` | Marks the throwaway demo task. |

Do not invent fields: `parse_task()` keeps unknown keys, but no command reads
them, and a hand-written duplicate or stray indented line makes the file invalid
(`ai doctor` names it).

## Specs

Required sections: Intent, Behavior, Acceptance criteria, Out of scope, Status.
Acceptance criteria must be observable from outside the implementation. A spec
with no way to fail is not a spec.

## Git

- One task per branch is a good default. The branch name references the task:
  `feature/0001-add-invoice-export` (the type prefix is `feature`, `fix`, `chore`,
  `docs`, `refactor` or `hotfix`; `ai git start` creates it).
- The commit type list is the single source in this file: `feat`, `fix`,
  `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`
  (the same tuple the CLI accepts). `templates/git/commit-template.txt` refers
  here instead of repeating its own list.
- Commit messages describe the change, not the agent:
  `Add invoice CSV export`, not `AI changes`.
- `ai git commit` verifies staged paths against held leases automatically when
  the task declares `locks`/`scope_allowed`; `--no-verify` is the deliberate
  bypass and belongs in the task log. Ledger files (`tasks/`, `specs/`,
  `config/`, `docs/decisions/`) never need a lease.
- Do not force-push shared branches, do not rewrite published history.
- `ai check` must be green before a commit that claims completion.
- Never commit `runtime/` state, raw evidence dumps or secrets.

## Commands

- Verification is `ai check`. There is no second contract.
- `ai check --fast` is for the inner loop and is not evidence.
- **The per-task evidence record** is `ai check --task <id> --agent <n>`; it
  writes `runtime/state/evidence/<id>.jsonl`, which is what the review gate
  reads. `ai check` without `--task` is a workspace state check.
- `ai check --strict` is CI's global gate (warnings fail). It is not the
  per-task proof and agents must not paste it in place of one.
- `ai git finish` runs `ai check --strict --task <id>` before merging.
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
