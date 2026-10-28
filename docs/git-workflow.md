# Git workflow — small Gitflow for AI sessions

Git is the audit trail. A task is not finished because a session says so; it is
finished when its branch is merged with evidence. This workspace uses a small,
local Gitflow loop:

## When this workflow is required

Every task that changes files must use this workflow unless the user explicitly
asks not to use Git. Run `ai git setup` before file-changing work; it initializes
Git if `.git` is absent and creates the configured branches if needed. Then
claim the task and successfully start its task branch before the first edit. If
`ai git start` fails, stop before changing files and report the reason. Read-only
tasks do not need a branch.

If Git reports dubious ownership, do not treat the folder as non-Git and do not
run `git init`. Ask the user to approve adding only this checkout to Git's
`safe.directory`, then retry setup. Never use a wildcard trust entry.

```text
main ─────────────────────────────●──────────────● (production / hotfix)
        \                        /              /
develop  ●────●──────●────●──────●──────────────   (integration)
          \  /      \  /
   feature/0001   fix/0002                         (one task per branch)
```

- `productionBranch` (default `main`) holds released code.
- `integrationBranch` (default `develop`) collects reviewed work.
- Every task gets one branch from integration: `feature/`, `fix/`, `chore/`,
  `docs/`, `refactor/`.
- A hotfix branches from production and must be merged back to both
  production and integration.
- No command pushes, rewrites history, or force-deletes a branch.

Configure it in `config/workspace.json`:

```json
"git": {
  "integrationBranch": "develop",
  "productionBranch": "main",
  "branchTypes": ["feature", "fix", "chore", "docs", "refactor", "hotfix"],
  "commitTemplate": "templates/git/commit-template.txt",
  "merge": "no-ff",
  "deleteAfterMerge": true
}
```

## Setup before file-changing tasks

```sh
ai git setup
```

This sets the local `commit.template` to
`templates/git/commit-template.txt` and creates the configured production and
integration branches when missing. If no Git repository exists, it initializes
one. If a repository has no commits, setup previews the non-ignored project
files and asks for an exact interactive confirmation before creating the
initial production commit. Non-interactive setup and declined confirmation do
not stage or commit project files. Setup is idempotent; run it when first using
this workspace in a clone, and rerun it if setup status is unknown.

The template is also a contract:

```text
<type>(<scope>): <imperative subject>

Why:
- ...

What:
- ...

Task: 0001
Agent: implementer-1
Check: ai check --strict -> 0 errors, 0 warnings
```

## Required loop for each file-changing task

```sh
ai task claim 0001 --agent implementer-1
ai git start --task 0001 --agent implementer-1 --type feature

# edit only what the task owns
ai check --fast
git add <only the files you own>
ai git verify --strict
ai git commit --task 0001 --agent implementer-1 --type feat --scope export \
  --message "add CSV export endpoint" --body "Closes the export gap for admins."

ai check --strict
ai task review 0001 --agent implementer-1
ai task release 0001 --agent implementer-1
```

Then let a different session verify it. `ai task review` records the state;
`ai task release` frees the claim while preserving that state. The reviewer (or
QA) merges:

```sh
# reviewer session, after reading the spec and diff
ai git finish --task 0001 --agent reviewer-a
ai task done 0001 --agent reviewer-a
```

`ai git finish` refuses to merge unless:

1. the task is `review` or `done` (or `--force` is recorded as an exception);
2. the working tree is clean;
3. `ai check --strict` passes;
4. the task branch exists.

It merges with `--no-ff`, deletes the branch when `deleteAfterMerge` is true,
and records `merged_into` / `merged_at` on the task. It never pushes.

## Branch naming

```text
<type>/<task-id>-<slug>
feature/0007-csv-export
fix/0012-empty-vat-id
hotfix/0015-login-500
```

The slug is derived from the task title. Branch names are local to the clone;
with several agents, use git worktrees so they do not share a checkout:

```sh
git worktree add ../proj-0007 -b feature/0007-csv-export develop
git worktree add ../proj-0008 -b feature/0008-import develop
```

## Commit rules

- One logical change per commit; stage only paths you own.
- Conventional Commit type plus an imperative subject: `feat:`, `fix:`,
  `docs:`, `refactor:`, `test:`, `chore:`.
- Keep `Task:` and `Agent:` trailers. `ai git commit` adds them.
- Do not commit scratch files, secrets, or another agent's work.
- A commit is not a merge. Do not merge into integration from an implementer
  session in `strict` mode; the reviewer/QA does it.

## Hotfix

```sh
ai git start --task 0015 --agent fixer --type hotfix
# fix, test, commit
ai git finish --task 0015 --agent reviewer-a
```

`start --type hotfix` bases the branch on production. After the production
merge, merge the same branch into integration before deleting it; `ai git
finish` only handles one integration merge, so keep the branch until both
merges are done (`deleteAfterMerge: false` for hotfix repositories).

## What agents must not do

- Do not commit directly on `main`, `develop`, or another task's branch.
- Do not use `git commit --amend` on a commit you did not create in this session.
- Do not force-push, rebase shared branches, or delete live locks to unblock
  yourself.
- Do not merge your own task without a separate verification session.
