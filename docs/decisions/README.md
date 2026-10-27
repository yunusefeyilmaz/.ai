# Decisions

Architecture Decision Records (ADRs) capture *why* a choice was made, so the
reason survives the session that made it.

## When to write one

- A choice that is expensive to reverse (storage, protocol, trust boundary).
- A choice that future agents will otherwise re-litigate.
- A deliberate deviation from a rule in `AGENTS.md`.

A task can end without an ADR. A lasting decision cannot.

## Format

`NNNN-<slug>.md`, numbered from `0001`:

```md
# NNNN - Title

- Status: proposed | accepted | superseded by NNNN
- Date: YYYY-MM-DD
- Deciders: names or agents

## Context
What forces are at play? What breaks if we do nothing?

## Decision
The choice, in the active voice.

## Consequences
What becomes easier, what becomes harder, what is now forbidden.

## Alternatives
What else was considered and why it lost.
```

## Rules

- Records are append-only; supersede rather than rewrite.
- Keep them short enough to read in one sitting.
- Link the task that produced the decision.
- Decisions about this workspace itself live here too.
