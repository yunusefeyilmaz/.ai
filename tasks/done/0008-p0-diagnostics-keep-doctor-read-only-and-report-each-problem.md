---
id: 0008
title: "P0 diagnostics: keep doctor read-only and report each problem once"
status: done
owner: null
priority: high
spec: specs/active/0008-p0-diagnostics-keep-doctor-read-only-and-report-each-problem.md
created: 2026-10-29T07:53:49Z
updated: 2026-10-29T08:06:28Z
lock: null
depends_on: 0002
branch: null
merged_into: develop
merged_at: 2026-10-29T08:04:47Z
---

# 0008 - P0 diagnostics: keep doctor read-only and report each problem once

## Intent

The 0002 review left two gaps between the promise and the behavior. Plain
`ai doctor` is documented as a reader, yet listing locks and handoff markers
each create the runtime directories, so a diagnostic run quietly repairs empty
state. And a missing config is reported twice, once with the right `--fix` hint
and once with a `git checkout` hint that cannot work in a copied or ignored
install.

Diagnosis should observe, not change. `--fix` stays the only writing path, and
each problem gets exactly one finding with one correct next step.

## Acceptance criteria

- [ ] `ai doctor` and `ai check` no longer create directories; with `runtime/`
      removed, a plain `doctor --json` exits 1 and leaves `runtime/` absent.
- [ ] A missing `config/workspace.json` produces exactly one finding, with the
      `ai doctor --fix` hint.
- [ ] A missing framework file in a subfolder install is hinted as a restore
      from the workspace copy, not as `git checkout` in the host repository.
- [ ] `ai doctor --fix` still recreates the runtime tree and the config.
- [ ] The new regressions are covered in `tests/test_doctor.py` and
      `ai check --strict` is green.

## Plan

Spec: `specs/active/0008-p0-diagnostics-keep-doctor-read-only-and-report-each-problem.md`

1. Give the lock and handoff readers an `ensure` switch; checks pass false.
2. Let the config block own the missing-config finding; skip it in the required
   path loop.
3. Choose the restore hint from the install shape.
4. Add tests and a changelog entry.

## Notes

## Log

- 2026-10-29T07:53:49Z created
- 2026-10-29T07:53:49Z claimed by implementer
- 2026-10-29T07:53:50Z created branch fix/0008-p0-diagnostics-keep-doctor-read-only-and from develop by implementer
- 2026-10-29T07:58:19Z implementation ready: `python -m unittest discover -s tests -q` -> 24 tests OK; `ai check --strict` -> 0 errors, 0 warnings
- 2026-10-29T07:58:38Z committed: fix(doctor): keep diagnostics read-only and deduplicate findings
- 2026-10-29T07:58:43Z submitted for independent review by implementer
- 2026-10-29T07:58:43Z released by implementer
- 2026-10-29T07:58:45Z committed: chore: record review-ready state for 0008
- 2026-10-29T08:04:47Z merged fix/0008-p0-diagnostics-keep-doctor-read-only-and into develop by codex
- 2026-10-29T08:06:28Z marked done by codex
