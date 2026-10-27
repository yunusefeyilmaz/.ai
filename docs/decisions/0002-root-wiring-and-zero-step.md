# 0002 - Root wiring is a one-time adopt, then zero-step clones

- Status: accepted
- Date: 2026-10-27
- Deciders: project maintainers

## Context

AI coding tools auto-load instructions only from fixed project-root locations:
`AGENTS.md`, `CLAUDE.md`, `.cursor/rules/*.mdc`, `.github/copilot-instructions.md`.
A workspace cloned into `.ai/` is therefore invisible until something points the
root at it. Requiring every clone to run a command contradicts the goal of
"clone and work".

## Decision

Offer two install shapes:

1. **Template install** — the workspace *is* the project root. The root
   `AGENTS.md` is the signpost; nothing to run. Truly zero-step.
2. **Subfolder install** — run `ai adopt` once, commit the four root files it
   writes (managed blocks), and every later clone is zero-step.

`ai adopt --check` is the CI guard for the subfolder shape. The Markdown protocol
remains usable without Python by copying the blocks by hand.

## Consequences

- The template shape is the only truly no-command install; the subfolder shape
  has exactly one setup commit.
- Root files stay short: they contain a pointer, not a copy of the rules.
- Updating the managed block is idempotent and `--force` rewrites it.
- A project can switch shapes later without rewriting tasks or specs.

## Alternatives

- **Symlinks from root to `.ai/`.** Fragile on Windows and often ignored by
  tools; not portable.
- **A CLI hook that runs on every clone.** Requires trusting git hooks and a
  local runtime; adds a failure mode to the first session.
- **Duplicate the full rules in every root file.** Guarantees drift between
  copies.
