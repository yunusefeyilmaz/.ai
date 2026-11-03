---
status: draft
task: 0012
approved_by: null
approved_on: null
---

# Remove the GUIDE and orchestration contradictions about checks and review claims

## Intent

GUIDE and docs/orchestration.md describe behavior the code no longer has, so an agent that reads them follows the wrong rule.

## Behavior

### Changed

<!-- What will be different. Be concrete. -->

### Preserved

<!-- What must not change. Explicitly list existing behavior at risk. -->

## Acceptance criteria

- [ ] GUIDE states that `ai check --strict --task` records per-task evidence
- [ ] docs/orchestration.md says the reviewer claims the task before writing a verdict
- [ ] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
