# Adapters

`.ai/` is the source of truth. An adapter is a thin pointer that tells one tool
where the source of truth is. Rules are never duplicated here.

| Adapter | Tool | Wiring file in the project |
|---------|------|----------------------------|
| `claude-code/` | Claude Code | `CLAUDE.md` |
| `cursor/` | Cursor | `.cursor/rules/ai-workspace.mdc` |
| `github-copilot/` | GitHub Copilot | `.github/copilot-instructions.md` |
| `codex/` | Codex | `AGENTS.md` (native) |
| `generic/` | Anything else | paste `generic/README.md` |

`ai adopt` writes the four root files automatically with a managed block
(`<!-- ai-workspace:start --> ... <!-- ai-workspace:end -->`) and adds them plus
`.ai/` to the host project's `.gitignore`. These are local files; each clone
runs `ai adopt` again. `ai adopt --check` reports missing pointers or ignore
rules. The adapters below remain the manual fallback.

## Adding an adapter

1. Create `adapters/<tool>/README.md` with: how to wire, the exact file to
   create, and which features the tool supports.
2. Add `adapters/<tool>/adapter.json`:

```json
{
  "tool": "tool-name",
  "entry": "path/in/project",
  "autoload": ["entry"],
  "supports": ["auto-load", "subagents", "hooks"]
}
```

3. Do not copy rules from `docs/` into the adapter. Point at them.

## Principle

The adapter is disposable. If a tool changes its configuration format, only the
adapter changes; the workspace, the protocol and the CLI stay the same.
