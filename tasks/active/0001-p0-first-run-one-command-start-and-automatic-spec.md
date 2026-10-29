---
id: 0001
title: "P0 first-run: one-command start and automatic spec"
status: review
owner: null
priority: high
spec: specs/active/0001-first-run.md
created: 2026-10-29T06:55:07Z
updated: 2026-10-29T07:10:49Z
lock: null
depends_on: null
branch: null
merged_into: develop
merged_at: 2026-10-29T07:10:49Z
---

# 0001 - P0 first-run: one-command start and automatic spec

## Intent

The README walkthrough asks a newcomer to run nine commands before the first
edit. Most of that is setup the tool can do itself. Reduce first use to one
command that leaves a claimed, specified task on a task branch, without adding
another configuration surface.

## Acceptance criteria

- [x] `ai start` in a fresh root-template workspace prepares directories and
      config, reports install shape and Git state, creates one starter task with
      a spec, and exits 0.
- [x] `ai start --agent <name>` also claims the starter task and prints the two
      commands needed to begin editing.
- [x] `ai start` never overwrites existing tasks and does not create a starter
      task when any task already exists. With no Git commit it does not prompt;
      it prints `ai git setup` as the next step instead.
- [x] `ai task new` writes `specs/active/<id>-<slug>.md` and links it from the
      task `spec` field. `--no-spec` suppresses it; an explicit `--spec` is
      linked without being overwritten.
- [x] In `lite` mode a freshly claimed task with no checkpoint produces no
      `ai check` warning; `strict` still warns. A checkpoint older than
      `handoff.warnAfterMinutes` warns in both modes.
- [x] README, GUIDE, CHANGELOG and `ai capabilities` describe `ai start`.
- [x] `tests/test_start.py` covers the criteria above and passes in `ai check`.

## Plan

1. Refactor task creation so `task new` and `start` share one path.
2. Add `ai start` with `--agent`, `--no-demo`, `--json`.
3. Add the lite-mode checkpoint grace to `collect_checks`.
4. Update docs, capabilities and version; add the test module and wire it into
   `config/workspace.json` checks.

## Notes

## Log

- 2026-10-29T06:55:07Z created
- 2026-10-29T06:55:15Z claimed by implementer
- 2026-10-29T06:56:02Z created branch feature/0001-p0-first-run-one-command-start-and-autom from develop by implementer
- 2026-10-29T07:05:35Z committed: feat(onboarding): add one-command start and automatic specs
- 2026-10-29T07:06:04Z submitted for independent review by implementer
- 2026-10-29T07:06:04Z released by implementer
- 2026-10-29T07:06:09Z committed: chore: record review-ready state
- 2026-10-29T07:09:39Z reviewed by reviewer: PASS. Commands: `ai doctor --strict` -> 0 errors, 0 warnings; `ai check --strict` -> 0 errors, 0 warnings; `python -m unittest discover -s tests -v` -> 13 tests OK; independent scratch-copy checks for every spec acceptance criterion passed.
- 2026-10-29T07:09:57Z committed: docs: record independent review evidence
- 2026-10-29T07:10:49Z merged feature/0001-p0-first-run-one-command-start-and-autom into develop by reviewer
