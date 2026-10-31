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
tasks do not need a branch. `ai git start` ignores uncommitted `tasks/` and
`specs/` files, because a fresh claim is ledger state; product files must be
clean.

If Git reports dubious ownership, do not treat the folder as non-Git and do not
run `git init`. Ask the user to approve adding only this checkout to Git's
`safe.directory`, then retry setup. Never use a wildcard trust entry.

```text
master ─────────────────────────────●──────────────● (production / hotfix)
        \                        /              /
develop  ●────●──────●────●──────●──────────────   (integration)
          \  /      \  /
   feature/0001   fix/0002                         (one task per branch)
```

- `productionBranch` (default `master`) holds released code.
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
  "productionBranch": "master",
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
one, with `HEAD` set to the configured production branch even when Git's
installation default is named `master`. A standalone checkout of this
framework (where `.ai` itself is the Git root) is treated as the project root;
an adopted `.ai` subfolder continues to use its host project root. Branches
without a commit are not valid bases; setup creates missing branches from
resolved commit IDs. If a
repository has no commits, setup previews the non-ignored project
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

The slug is derived from the task title. Branch names are local to the clone.

## Worktrees (parallel workers)

Two workers cannot share one checkout: a branch switch changes every file under
both. With `git.isolation = worktree` (set automatically by
`ai setup --set workers=N`, N > 1) each claimed task gets its own checkout:

```
project/
├── .ai/                      <- the single shared workspace (tasks, locks, runtime, config)
│   ├── ai.py
│   └── worktrees/
│       ├── feature-0001-login/      <- task 0001, branch feature/0001-login
│       └── feature-0002-payment/    <- task 0002, branch feature/0002-payment
└── src/ ...                  <- main checkout: develop, never edited by workers
```

| Data | Where |
|------|-------|
| Task definitions, ownership, locks, checkpoints, evidence | the one main `.ai/` |
| Product files being edited, Git index and branch | the task's worktree |
| Project checks (`ai check`, `ai task review`) | run inside the task's worktree |

How it works:

- `ai task claim|next` (or `ai git start`) runs `git worktree add` from `develop`,
  records `worktree:` in the task and prints the path. The main checkout is not
  touched, so it does not need to be clean.
- A worktree has no `.ai/` of its own (the workspace is git-ignored in the host).
  The worker runs the shared CLI by absolute path (printed at claim time, also in
  the `AGENTS.md`/`CLAUDE.md` briefing the workspace drops into the worktree).
  `ai git commit|verify`, `ai check --task`, `ai checkpoint|resume` and
  `ai task review` find the task's worktree themselves, whatever the caller's
  directory.
- The worktrees folder and the briefing files are added to `info/exclude`, so
  neither the main checkout nor the worktree shows them in `git status`.
- `ai git finish` (the reviewer) requires a committed worktree, runs the checks
  there, merges the branch into `develop` in the main checkout, then removes the
  worktree and the branch.
- `ai worktree list` shows each worktree and its task; `ai worktree prune`
  removes those of finished or discarded tasks (it keeps any with uncommitted
  changes unless `--force`); `ai doctor` warns about orphans.
- File locks and scope still apply: two workers cannot lock overlapping paths, so
  they rarely conflict at merge time. When they do, the second `ai git finish`
  fails safely (merge aborted); the producer rebases and the reviewer retries.

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

- Do not commit directly on `master`, `develop`, or another task's branch.
- Do not use `git commit --amend` on a commit you did not create in this session.
- Do not force-push, rebase shared branches, or delete live locks to unblock
  yourself.
- Do not merge your own task without a separate verification session.
