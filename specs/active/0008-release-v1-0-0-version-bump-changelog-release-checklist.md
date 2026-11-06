---
status: draft
task: 0008
approved_by: null
approved_on: null
---

# Release v1.0.0: version bump, changelog, release checklist

## Intent

Ship the first release whose claims are true: bump version, record the changelog, and prove the gates green.

## Behavior

### Changed

- `VERSION` and `lib/core/paths.py` report `1.0.0`.
- `CHANGELOG.md` gains a `[1.0.0]` section: no new features, only reliability fixes, plus the lock semantics change.
- Release notes include the 0.9.9 -> 1.0.0 upgrade note.

### Preserved

- No command surface is added or removed in this task.
- CI matrix and check definitions stay unchanged.

## Acceptance criteria

- [x] VERSION and lib/core/paths.py both report 1.0.0
- [x] CHANGELOG has a 1.0.0 entry that states there are no new features, only reliability fixes, and lists the lock semantics change
- [x] ai version prints 1.0.0
- [x] ai doctor --strict and the full check suite are green on the release commit
- [x] Release notes mention the 0.9.9 to 1.0.0 upgrade note for lock semantics
- [x] Tests cover the new behavior and pass

## Out of scope

- Publishing to PyPI or any package registry.
- Changing the plugin/adapter API.

## Status

draft -> in progress -> shipped.
