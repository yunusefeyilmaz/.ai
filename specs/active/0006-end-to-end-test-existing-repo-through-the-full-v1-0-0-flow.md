---
status: draft
task: 0006
approved_by: null
approved_on: null
---

# End-to-end test: existing repo through the full v1.0.0 flow

## Intent

No test covers an existing Git repo end to end, which is why onboarding, the check gate and the criteria gate all regressed silently. One flow test locks them together.

## Behavior

### Changed

- New `lib/tests/test_e2e_flow.py` builds a throwaway Git repo with existing commits, then drives adopt, setup, plan, claim, checkpoint, criterion ticks, commit, check, review, finish and done.
- The test asserts HEAD is `develop` after setup, the tree is clean after done, the configured check really ran, and the archived spec is `status: shipped` with every criterion ticked.
- A negative assertion proves review is refused while a criterion is unticked.

### Preserved

- Existing unit tests keep running unchanged.
- The test uses only stdlib and the repo's own test harness (no network, no global Git config changes).

## Acceptance criteria

- [x] One test builds an existing Git repo, runs adopt, setup, plan, claim, checkpoint, criterion ticks, commit, check, review, finish and done
- [x] The test asserts HEAD is develop after setup, the tree is clean after done, the checks really ran, and the spec is archived as shipped with all criteria ticked
- [x] The test asserts review is refused while a criterion is unticked (negative case)
- [x] The test runs green on the CI matrix
- [x] Tests cover the new behavior and pass

## Out of scope

- Testing every command; this is one happy path plus the two critical refusals.
- Replacing existing focused unit tests.

## Status

draft -> in progress -> shipped.
