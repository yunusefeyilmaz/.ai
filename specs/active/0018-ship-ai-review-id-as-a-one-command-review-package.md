---
status: approved
task: 0018
approved_by: orchestrator
approved_on: 2026-11-03
---

# Ship ai review <id> as a one-command review package

## Intent

A reviewer has to assemble the same five things every time — the task, its spec and acceptance criteria, the diff of the branch, the check evidence, and the transition history — from five different commands and a file read. Doing that partially is easy, and doing it repeatedly costs the most tokens of any role in the loop. One command should hand the reviewer everything they need to decide.

## Behavior

### Changed

New top-level command, implemented in `lib/cmd/review.py` and picked up automatically by `lib/cmd/discover.py`:

```
ai review <id> [--stat] [--max-lines N] [--json]
```

Output sections, in this order:

1. Header: task id/title/status/owner/submitted_by/priority, branch and worktree (or "no branch").
2. Spec: path, and the acceptance criteria parsed out of it as a list, plus a note when the spec is missing or still the template.
3. Diff: `git diff <merge-base>..HEAD` for the task's branch against `git.integrationBranch`, prefixed by `--stat` output. `--stat` alone stops after the summary; `--max-lines N` truncates the patch and appends a visible `[truncated: N of M lines]` marker.
4. Evidence: the latest recorded check for this task — state (`green`/`partial`/`stale`/`missing`), the HEAD it belongs to, whether it was on the current HEAD, and the per-command results.
5. History: the same transition lines `ai history <id>` prints.
6. Checklist: a fixed, short list of what the reviewer must verify (criteria met, scope respected, check evidence on this HEAD, no uncommitted changes), ending with the exact next command (`ai task next --review --agent <you>`).

`--json` returns the same content as structured fields (`task`, `spec`, `criteria`, `diff`, `evidence`, `history`, `checklist`).

Work happens in the task's checkout when the task has a worktree (`repo.in_task`), so the diff matches what the worker produced.

### Preserved

- `ai task review <id>` (the transition) is untouched; `ai review` claims nothing and writes nothing.
- `ai brief` keeps its external-assistant purpose and output.
- `ai history` output format.

## Acceptance criteria

- [ ] `ai review <id>` prints one package containing task state, the linked spec with its acceptance criteria, the branch diff against the integration branch, the recorded check evidence and the transition history
- [ ] the package ends with a short checklist naming what the reviewer must verify, and a failing/missing evidence record is called out explicitly
- [ ] `--stat` limits the diff to a summary and `--max-lines N` truncates the full diff with a visible marker; `--json` returns the same data structured
- [ ] the command is read-only: it claims nothing, writes nothing and exits 1 with an actionable message for an unknown task id
- [ ] the new command is registered, described in `ai capabilities` and listed in AGENTS.md and the review docs
- [ ] Tests cover the new behavior and pass

## Out of scope

- Approving or rejecting from `ai review` (that stays `ai task done` / `ai task request-changes`).
- Fetching a review into a worktree.
- PR templates or remote hosting.

## Status

shipped when green.
