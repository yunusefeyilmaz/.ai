---
status: approved
task: 0016
approved_by: orchestrator
approved_on: 2026-11-03
---

# Add needs_human and next_args to ai now --json

## Intent

An agent reading `ai now --json` must not have to interpret prose to know whether it should act or ask the user, and NEXT must be executable with the caller's own agent name. Today the JSON carries a `recommended` object with a sentence of justification; a harness that wants to drive the CLI has to parse that sentence and re-invent the argv.

## Behavior

### Changed

- `ai now --json` publishes `schema: 2` and four new top-level keys:
  - `needs_human` (bool): true when the correct next move is to ask the user, false when the agent can act.
  - `question` (string|null): the sentence to put to the user when `needs_human` is true, null otherwise.
  - `next_args` (list[str]): the NEXT command as argv tokens without the leading `ai`, so `subprocess` can run it unchanged.
  - `blocker` (string|null): the reason there is no action to take, when there is none.
- `needs_human` is true, and `question` non-empty, for every recommendation that ends in a question to the human: unconfirmed setup, "nothing is ready", and delivered work awaiting a go-ahead.
- `next_args` is derived from the same value that prints NEXT, so it never disagrees with the printed line, and it carries the caller's agent name when `--agent` was passed (no `<n>` placeholder remains).
- The recommendation builder is one function used by both the text and JSON renderers, so a new recommendation cannot set a command but forget the flags.

### Preserved

- The line structure of the human-readable `ai now` output: header, YOU, NEXT, WHY, ALSO/HANDOFF/REVIEW/READY/WAIT/BUSY, More.
- The existing `recommended` object and every other key of the JSON payload; consumers that only read `recommended` keep working.
- `ai context --json` (it shares `overview.build`, but not the new now-only fields).
- `<n>` may still appear in the *text* NEXT line when no `--agent` was given; only the JSON `next_args` is required to be concrete when an agent was supplied.

## Acceptance criteria

- [ ] `ai now --json --agent X` publishes schema 2 with `needs_human` (bool), `question` (string or null), `next_args` (list of argv tokens without the leading `ai`) and `blocker` (string or null)
- [ ] `needs_human` is true and `question` is non-empty whenever the next step is a question to the user (unconfirmed setup, nothing ready, delivered work awaiting a go-ahead) and false while a claimable or claimed task exists
- [ ] `next_args` is concrete when `--agent` is given (no `<n>` placeholder) and reconstructs the printed NEXT command
- [ ] the human-readable `ai now` output is unchanged in shape and still shows NEXT with a runnable command
- [ ] Tests cover the new behavior and pass

## Out of scope

- Session tokens or any real identity for `--agent`.
- Renaming or reshaping `recommended`.
- A `--json` schema for `ai context`.

## Status

shipped when green.
