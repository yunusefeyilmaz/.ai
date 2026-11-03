---
status: draft
task: 0006
approved_by: null
approved_on: null
---

# Parse flow-style front matter lists instead of dropping dependencies

## Intent

Models routinely emit depends_on: [0001, 0002]; the hand-written parser keeps that as one opaque string, so dependencies and scope silently vanish.

## Behavior

### Changed

- The front-matter parser accepts YAML-style flow lists on any key: `depends_on: [0001, 0002]`, `locks: ["lib/a.py", "lib/b.py"]` and an empty `[]`.
- Flow lists normalize to the canonical comma-separated string the rest of the workspace already reads, so dependencies, scope and locks survive a model-written task file.
- `format_value` writes a Python list/tuple in the same comma-separated form instead of a Python repr.
- An unterminated flow list becomes a parser problem (`unterminated flow list`) that `frontmatter_problems` and `ai doctor` report; the value is not dropped silently.

### Preserved

- Scalar, quoted, bool/null and `|`/`>` block values keep their current behavior.
- Duplicate-key, missing-colon and stray-indentation problems keep their current messages.
- Dependency validation and task ordering are unchanged; they still consume the same comma-separated strings.

## Acceptance criteria

- [ ] `python lib/tests/run.py test_frontmatter_lists` is green
- [ ] `depends_on: [0001, 0002]` parses to two dependency ids and `board_dependencies` returns both
- [ ] quoted items, spacing and an empty `[]` are handled without leaving brackets in the value
- [ ] an unterminated flow list is reported as a front-matter problem instead of being silently accepted
- [ ] block and quoted scalar front matter keeps its current behavior
- [ ] Tests cover the new behavior and pass

## Out of scope

<!-- What this work will not do. Prevents scope creep. -->

## Status

<!-- draft -> approved -> in progress -> shipped. Update as the work moves. -->
