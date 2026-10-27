# Specs

One spec per piece of work that changes behavior. A spec is cheaper than a wrong
implementation.

```
specs/
├── active/    # proposed or in-progress work
├── done/      # shipped; immutable
└── TEMPLATE.md
```

## Rules

- No spec, no code — for behavior changes.
- Acceptance criteria are testable from outside the implementation.
- A spec that cannot fail is not a spec.
- Link the spec from the task (`spec` field and `## Plan`).
- When shipped, move it to `done/`. Do not edit it afterwards; supersede it.

## Naming

`specs/active/<task-id>-<slug>.md` when tied to a task, otherwise a descriptive
slug. Keep the `Status` line in sync with reality.
