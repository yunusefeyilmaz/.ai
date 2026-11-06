---
id: 0004
title: "No silent green: fail loudly when the project has no checks"
status: done
owner: evren-deep-seek-reviewer
priority: medium
spec: specs/done/0004-no-silent-green-fail-loudly-when-the-project-has-no-checks.md
depends_on: null
scope_allowed: "lib/cmd/doctor.py, lib/config/settings.py, lib/git/flow.py, lib/tests/test_check_gate.py, lib/tests/test_review_gate.py, lib/tests/test_start.py, lib/tests/test_workflow.py"
scope_forbidden: null
locks: "lib/cmd/doctor.py, lib/config/settings.py, lib/git/flow.py, lib/tests/test_check_gate.py, lib/tests/test_review_gate.py, lib/tests/test_start.py, lib/tests/test_workflow.py"
branch: null
created: 2026-11-04T08:14:04Z
updated: 2026-11-05T20:00:50Z
lock: null
submitted_by: evren-deep-seek
merged_into: develop
merged_at: 2026-11-05T19:56:20Z
reviewed_by: evren-deep-seek-reviewer
reviewed_at: 2026-11-05T20:00:50Z
---

# 0004 - No silent green: fail loudly when the project has no checks

## Intent

`ai check` looks successful when the project has no checks configured, and a review can pass on that empty evidence. An empty gate must be visible, not silent.

## Acceptance criteria

- [ ] `ai check` exits non-zero with an actionable message when no project checks are configured
- [ ] An explicit opt-out (or documented flag) exists for projects that intentionally run no checks, and it is printed in the output
- [ ] `ai task review` cannot pass on an empty check result in strict mode
- [ ] Regression tests cover both the refusal and the opt-out
- [ ] Tests cover the new behavior and pass

## Plan

Spec: `specs/active/0004-no-silent-green-fail-loudly-when-the-project-has-no-checks.md`

<!-- Filled by the planner. -->

## Notes

- The plan declared `lib/cmd/check.py`, but the `check` command has always lived
  in `lib/cmd/doctor.py` entirely; `lib/tests/test_check_gate.py` is new. The
  user approved widening `scope_allowed`/`locks` to `lib/cmd/doctor.py` and
  `lib/git/flow.py`, plus the existing tests that pinned the old silent pass.
- `ai check` now refuses (exit 1, actionable finding) when no runnable project
  checks are configured. Opt-outs, both printed as `ALLOW-EMPTY`: the explicit
  `--allow-empty` flag, and the persistent `workflow.requireCheck = false`
  written by `ai setup --set checks=no`.
- An empty run no longer records full/green evidence (`ran_commands=false`), so
  `ai resume` reports PARTIAL instead of "still valid".
- `ai git finish` runs its internal `ai check --strict`; it now passes
  `--allow-empty` only when `gates.check_required()` is false, keeping merges
  possible in workspaces that never opted into verification while still
  refusing empty proof in strict/required mode.

## Log

- 2026-11-04T08:14:04Z | chief-1 | - -> todo | created
- 2026-11-05T09:52:52Z | opencode-1 | todo -> in_progress | claimed
- 2026-11-05T09:52:53Z | opencode-1 | in_progress -> todo | claim rolled back | the task branch could not start
- 2026-11-05T18:08:05Z | evren-deep-seek | todo -> in_progress | claimed
- 2026-11-05T18:08:06Z created branch feature/0004-no-silent-green-fail-loudly-when-the-pro from develop by evren-deep-seek
- 2026-11-05T19:12:15Z committed: feat: refuse an empty check gate unless the project opts out
- 2026-11-05T19:15:40Z checkpoint by evren-deep-seek (checkpoint, ?%)
- 2026-11-05T19:15:55Z | evren-deep-seek | in_progress -> review | submitted for independent review | check passed @f38b0baa by evren-deep-seek (tests passed, ruff passed, mypy passed)
- 2026-11-05T19:20:45Z | evren-deep-seek-reviewer | review -> review | claimed
- 2026-11-05T19:54:33Z committed: chore(task): record review handover for 0004
- 2026-11-05T19:56:20Z merged feature/0004-no-silent-green-fail-loudly-when-the-pro into develop by evren-deep-seek-reviewer
- 2026-11-05T20:00:50Z | evren-deep-seek-reviewer | review -> done | approved | check passed @71420e99 by evren-deep-seek-reviewer (tests passed, ruff passed, mypy passed)
