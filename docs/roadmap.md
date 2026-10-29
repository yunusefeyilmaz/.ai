# Roadmap

The workspace is judged by how little it asks of a person before useful work.
The order below follows that rule: adoption first, proof second, measurement
third, extras last. Every item names the observable result, not the feature.

| Order | Task | Priority | Success signal |
|-------|------|----------|----------------|
| 1 | `0003` reliability suite | P0 | Concurrency, expiry and recovery are proven by automated tests. |
| 2 | `0004` metrics ledger | P1 | Workflow claims are backed by numbers from real tasks. |
| 3 | `0005` adapter contract | P1 | A new agent or CI provider plugs in without touching the core. |
| 4 | `0006` visibility board | P2 | A blocked session explains itself without reading logs. |

## Guardrails

- **Lite stays minimal.** A small task should need a claim, an edit and a
  verification. Extra ceremony is opt-in or belongs to `strict`.
- **No new state without a reader.** Every file the CLI writes must be consumed
  by a command or a check.
- **No new dependency.** Python standard library and Git only.
- **One command per common path.** Setup, resume and verification each get a
  single entry point; flags refine, they do not replace it.
- **Delete before adding.** If a step is not load-bearing, removing it beats
  automating it.

## Not planned

- A server, database, daemon or web dashboard.
- A hosted service or telemetry.
- A second task ledger or a second definition of done.
- Automatic merges without an independent reviewer.

## How this list changes

Each item is a task in `tasks/active/` with acceptance criteria. When an item
ships, its numbers and any reversal move to `CHANGELOG.md`; the list above keeps
only what is still ahead. New requests enter as tasks and must displace
something rather than extend the queue.
