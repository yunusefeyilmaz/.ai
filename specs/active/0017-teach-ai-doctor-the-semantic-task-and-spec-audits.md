---
status: approved
task: 0017
approved_by: orchestrator
approved_on: 2026-11-03
---

# Teach ai doctor the semantic task and spec audits

## Intent

`ai doctor` verifies the environment and some task-state invariants, but not the *meaning* of the ledger. An active task can sit with an unfilled spec, a dependency cycle, no owner and no branch, and doctor says nothing — so the failure surfaces later as an agent stuck or a claim refused for a reason nobody can see.

## Behavior

### Changed

`health.collect_checks()` gains four audits, each a `Finding` with an actionable hint:

1. **Unfilled spec** (warn): every task in `tasks/active` whose `spec:` reference is set must resolve to a file with at least one non-placeholder acceptance criterion. Reuses `lib.specs.spec.spec_problem`; the hint names the spec path and says the chief fills it. `spec: null` (deliberate `--no-spec`) stays exempt.
2. **Dependency cycle** (error): cycles among *active* tasks are detected over the `depends_on` graph (unknowable/unknown ids ignored, they already produce their own warning). The message names the cycle, e.g. `0016 -> 0017 -> 0016`; the hint says to break the edge.
3. **Unowned work** (warn): a task in `in_progress`, `review` or `blocked` with an empty `owner` is reported, with `ai task claim`/`ai recover --apply` as the hint.
4. **Branchless work** (warn): with `git.enabled` and a real repository, an active `in_progress` or `review` task with no `branch` is reported, hint `ai git start --task <id> --agent <owner>`.

Audits 1, 3 and 4 are warnings (doctor --strict fails on them, as it already does for warnings); a cycle is an error because the ready queue can never resolve it.

### Preserved

- Every existing finding and its level/hint text; findings keep their order relative to each other.
- `ai doctor --fix` does not attempt to repair any of the new findings (they need a human or chief decision), so `--fix` behavior is unchanged.
- A workspace with no active tasks still reports zero findings, and `ai doctor --strict` exits 0.
- `ai check` (which collects the same findings) does not start failing on a healthy repository.

## Acceptance criteria

- [ ] `ai doctor` warns about every active task whose spec is missing, unreadable or still the template, with the spec path and a fill-it hint
- [ ] `ai doctor` reports dependency cycles among active tasks as an error naming the cycle, and still reports unknown dependencies as before
- [ ] `ai doctor` warns about in_progress/review/blocked tasks with no owner, and about in_progress/review tasks with no branch while git is enabled, each with the next command as the hint
- [ ] a clean workspace with no active tasks still reports zero findings and `ai doctor --strict` exits 0
- [ ] Tests cover the new behavior and pass

## Out of scope

- Auto-repair of any new finding.
- Graph visualization (`ai task list --graph`).
- Changing `ai doctor --fix`.

## Status

shipped when green.
