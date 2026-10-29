---
status: shipped
task: 0002
approved_by: null
approved_on: null
---

# Actionable diagnostics

## Intent

`ai doctor` already finds real problems, but a newcomer only learns that
something is wrong, not what to do about it. Several findings even contain a
command inside prose, so the output cannot be parsed by an agent either.

Diagnosis is only useful when it names the safe repair. The same applies to the
repair itself: a broken workspace should be recoverable without hand-editing
files or guessing which of the findings are safe to act on. The change keeps
`doctor` a reader by default and makes repair an explicit, narrow operation.

## Behavior

### Changed

- Every finding carries a stable shape: `level` (`error`/`warn`), a message and
  an optional hint. Hints are concrete commands or file edits, never vague
  advice. Findings without a known safe repair keep an empty hint.
- Human output prints `fix: <hint>` under a finding that has one.
- `--json` keeps the existing `ok`/`errors`/`warnings` keys and adds a
  `findings` array of `{level, message, hint}` objects.
- `ai doctor --fix` runs only these repairs, in this order, before diagnosing:
  1. recreate missing runtime directories and their keep files;
  2. write `config/workspace.json` from `default_config()` when it is missing;
  3. in a subfolder install, write missing root adapter pointers and missing
     `.gitignore` entries.
  Each change is reported once as `FIXED <what>` and returned in `fixes`.
- `--fix` never rewrites an existing but invalid config, never removes a lock,
  never edits task or spec files, never touches Git, and never force-claims or
  force-releases anything. A corrupt config is still reported with a manual
  recovery hint.
- With `--fix`, the exit code is 0 only when no findings remain. Without
  `--fix`, the previous rule stays: errors fail, warnings fail only under
  `--strict`.
- A subfolder install now reports missing adapter pointers and missing ignore
  rules, so the repair is observable. These findings are warnings.

### Preserved

- `ai check` remains the gate and uses the same findings; its exit rules,
  `--fast`, `--no-commands` and JSON shape are unchanged apart from the added
  hints.
- `ai init`, `ai adopt` and `ai start` keep their current output and effects.
  `--fix` reuses their underlying helpers rather than adding a second path.
- A finding that cannot be repaired safely still fails the run; silence is never
  treated as success.
- No new dependency; Python standard library only.

## Acceptance criteria

- [x] A workspace missing `runtime/` reports `missing required path: runtime`
      with a hint, and `ai doctor --fix` recreates the runtime tree, reports the
      change, and exits 0.
- [x] A workspace missing `config/workspace.json` is reported with a hint and
      repaired by `--fix`; tasks, specs and the Git HEAD are byte-identical
      before and after.
- [x] A corrupt `config/workspace.json` is reported, `--fix` leaves it
      unchanged, and the command exits 1.
- [x] An orphan task lock is reported with a hint; `--fix` does not remove the
      lock, still reports the finding, and exits 1.
- [x] `ai doctor --fix --json` prints a `fixes` array and the remaining
      `findings`, and its exit code is 0 only when `findings` is empty.
- [x] A subfolder install with no root adapter pointers reports the missing
      adapters and `.gitignore` rules; `--fix` writes them and re-checks clean.
- [x] `ai doctor --json` keeps `ok`, `errors` and `warnings` and adds
      `findings` with hints.
- [x] `python -m unittest discover -s tests` passes and `ai check --strict` is
      green.

## Out of scope

- Repairing task front matter, renaming task files, or moving tasks between
  `active/` and `done/`.
- Deleting or expiring locks; `ai clean` and `ai recover` keep those jobs.
- Overwriting a config that exists but is invalid.
- Any interactive prompt, network call or new dependency.

## Status

Shipped. Independently verified by `reviewer` on 2026-10-29:
`ai doctor --strict` -> 0 errors, 0 warnings; `ai check --strict` -> 0 errors,
0 warnings (23 tests); `python -m unittest discover -s tests -v` -> 23 tests OK
on Python 3.9.10 and 3.10.6. Every acceptance criterion was re-checked in
scratch copies under `%TEMP%`: missing `runtime/` -> exit 1 with
`missing required path: runtime` (hint `ai doctor --fix`), `--fix` reported the
created runtime entries and exited 0 with no findings, and a second `--fix`
returned an empty `fixes` array; a missing config was recreated with task/spec
bytes and `git rev-parse HEAD` unchanged; a corrupt config stayed byte-identical
with exit 1 and a manual hint; an orphan lock survived `--fix` with the
`ai recover --apply` hint and exit 1; the subfolder install reported the four
adapter pointers and `.gitignore` rules, `--fix` wired them, and the re-check
exited 0. Safe-repair audit: `--fix` only creates missing directories, keep
files, config and append-only adapter blocks; it never rewrites an existing
config, removes a lock, or touches task, spec or Git data.
