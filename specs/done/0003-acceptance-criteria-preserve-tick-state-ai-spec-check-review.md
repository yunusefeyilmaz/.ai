---
status: shipped
task: 0003
approved_by: null
approved_on: null
---

# Acceptance criteria: preserve tick state, ai spec check, review gate, shipped spec

## Intent

Acceptance criteria are decorative: there is no command to tick them, the parser discards [x], ai review prints them without boxes, ai task review never reads them, and archived specs stay status: draft with every box empty. The product's core promise does not work.

## Behavior

### Changed

- `spec.acceptance_criteria` returns `[(ticked, text), ...]`, preserving `[ ]` vs `[x]`; existing callers that only need text use a thin wrapper.
- New `ai spec check <task-id> <n>` ticks criterion n (1-based, idempotent) and `ai spec show <task-id>` prints `[x]/[ ]` plus `done/total`.
- `ai task review` refuses while any real criterion is unticked and names them; generated "Tests cover..." line is treated like any other criterion.
- `ai review` renders criteria with their boxes and real progress; the Checklist section reflects spec state instead of a hardcoded `[ ]`.
- `ai task done` rewrites the archived spec to `status: shipped`.
- The task body no longer carries its own acceptance list; it points at the spec so there is one place to tick.

### Preserved

- `ai doctor` and the claim gate keep using the same parser, and placeholder criteria are still detected.
- Tasks created with `--no-spec` stay exempt.
- Existing spec frontmatter keys keep their meaning.

## Acceptance criteria

- [x] The spec parser preserves per-criterion ticked state instead of stripping [ ]/[x]
- [x] `ai spec check <id> <n>` ticks a criterion and `ai spec show <id>` prints each criterion with its box and a done/total count
- [x] `ai task review` refuses while any real (non-generated) criterion is unticked and names the unticked ones
- [x] `ai review` prints criteria as [x]/[ ] with progress, and Evidence/Checklist state reflects the spec instead of a hardcoded empty box
- [x] `ai task done` sets the archived spec to status: shipped
- [x] The duplicate acceptance list in the task body no longer competes with the spec (single source of truth, task body points at the spec)
- [x] Regression tests cover ticking, the review refusal, and the archived status
- [x] Tests cover the new behavior and pass

## Out of scope

- A rich text or GUI editor for specs.
- Changing the spec markdown format beyond the checkbox state and status line.
- Enforcing criteria at claim time (claim still only needs one real criterion).

## Status

draft -> in progress -> shipped.
