# Codex adapter

## Wire

Codex reads `AGENTS.md` natively. No extra file is required when `.ai/` is the
project root (template install).

For a subfolder install, run once:

```sh
.ai/ai adopt
```

This adds a managed block to the project's root `AGENTS.md` (and the other
adapter files) pointing at `.ai/AGENTS.md`. Adopted files are local and ignored;
each clone runs `ai adopt`.

## Notes

- Codex skills can wrap the task flow (`ai task new`, `ai task claim`,
  `ai check`). Keep them thin.
- Run review in a fresh session; Codex has no enforced read-only reviewer.
- Use `$`-prefixed project skills only if you also document them in `AGENTS.md`,
  because auto-loaded context is the only reliable channel.
