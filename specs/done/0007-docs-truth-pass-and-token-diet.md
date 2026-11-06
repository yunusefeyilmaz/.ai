---
status: shipped
task: 0007
approved_by: null
approved_on: null
---

# Docs truth pass and token diet

## Intent

README and GUIDE claim adopt ignores .ai/, AGENTS.md claims PID is diagnostic only, and a worker is told to read five documents before starting. Docs must match the code and fit a small context budget.

## Behavior

### Changed

- README and GUIDE describe the ignore rules the code actually implements.
- AGENTS.md states the real staleness rule and is cut to roughly 70 lines.
- `prompts/worker.md` requires at most one document before the first command.
- Command examples in the docs are checked by the existing doc test (or an equivalent) so they cannot drift again.

### Preserved

- All command names and flags stay as implemented; docs follow code, not the reverse.
- The Turkish/English split of existing docs is not restructured in this task.

## Acceptance criteria

- [x] README and GUIDE describe the actual ignore rules from lib/config/adopt.py
- [x] AGENTS.md describes the actual lock staleness rule and fits within the token target (~70 lines)
- [x] prompts/worker.md requires at most one document before the first command
- [x] Every command shown in the docs exists and runs (doc test covers it)
- [x] Doc tests pass
- [x] Tests cover the new behavior and pass

## Out of scope

- Rewriting docs into a website or generating docs from code.
- Translating all docs into another language.

## Status

draft -> in progress -> shipped.
