"""Documentation must not drift from the CLI, and the code must stay tidy.

`ai ...` commands written in any guide are checked against the real parser, so a
renamed command or a stale path breaks a test instead of misleading an agent.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import unittest
from pathlib import Path

from test_start import ROOT, WorkspaceCase, run

sys.path.insert(0, str(ROOT))

DOC_GLOBS = [
    "README.md", "AGENTS.md", "GUIDE.md", "CHANGELOG.md", "docs/*.md", "agents/*.md", "prompts/*.md",
    "tasks/README.md", "specs/README.md", "skills/README.md", "lib/README.md", "adapters/**/*.md",
]
STALE_PATHS = ("scripts/ai", "scripts\\ai", "lib/runtime/artifacts", "lib/tasks/active", "lib/specs/active")


def parser_tree() -> dict:
    import ai

    parser = ai.build_parser([])

    def walk(p) -> dict:
        for action in p._actions:
            if isinstance(action, argparse._SubParsersAction):
                return {name: walk(sub) for name, sub in action.choices.items()}
        return {}

    return walk(parser)


def code_snippets(text: str) -> list[str]:
    snippets = re.findall(r"```[^\n]*\n(.*?)```", text, flags=re.S)
    without_fences = re.sub(r"```.*?```", "", text, flags=re.S)
    return snippets + re.findall(r"`([^`\n]+)`", without_fences)


COMMAND = re.compile(r"(?:^|[\s`$(;&|])ai ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?")


class DocumentedCommandsTest(WorkspaceCase):
    def doc_files(self) -> list[Path]:
        files: list[Path] = []
        for pattern in DOC_GLOBS:
            files += sorted(ROOT.glob(pattern))
        return files

    def test_every_documented_ai_command_exists(self) -> None:
        tree = parser_tree()
        problems = []
        for path in self.doc_files():
            text = path.read_text(encoding="utf-8")
            for snippet in code_snippets(text):
                for line in snippet.splitlines():
                    for match in COMMAND.finditer(line):
                        top, second = match.group(1), match.group(2)
                        if top not in tree:
                            problems.append(f"{path.relative_to(ROOT)}: unknown command `ai {top}`")
                        elif second and tree[top] and second not in tree[top]:
                            problems.append(f"{path.relative_to(ROOT)}: `ai {top}` has no subcommand `{second}`")
        self.assertEqual(sorted(set(problems)), [])

    def test_no_stale_paths_in_the_guides(self) -> None:
        problems = []
        for path in self.doc_files():
            # CHANGELOG records what the layout used to be; rewriting history to
            # satisfy a path check would make the log lie.
            if path.name == "CHANGELOG.md":
                continue
            text = path.read_text(encoding="utf-8")
            for stale in STALE_PATHS:
                if stale in text:
                    problems.append(f"{path.relative_to(ROOT)} mentions {stale}")
        self.assertEqual(problems, [])

    def test_adopt_ignore_rules_match_the_docs(self) -> None:
        from lib.config.adopt import ADOPT_IGNORE_ENTRIES

        self.assertIn(".ai/runtime/", ADOPT_IGNORE_ENTRIES)
        self.assertIn(".ai/worktrees/", ADOPT_IGNORE_ENTRIES)
        self.assertNotIn(".ai", {entry.strip().strip("/") for entry in ADOPT_IGNORE_ENTRIES})
        for name in ("README.md", "GUIDE.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn(".ai/runtime/", text, f"{name} omits .ai/runtime/")
            self.assertIn(".ai/worktrees/", text, f"{name} omits .ai/worktrees/")
            for number, line in enumerate(text.splitlines(), 1):
                if ".gitignore" in line:
                    self.assertNotIn(
                        "`.ai/`",
                        line,
                        f"{name}:{number} claims a blanket .ai/ ignore that adopt does not write",
                    )

    def test_agents_md_is_compact_and_states_the_staleness_rule(self) -> None:
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertLessEqual(len(lines), 85, f"AGENTS.md has {len(lines)} lines; keep it near 70")
        self.assertIn("staleAfterSeconds", text)
        self.assertIn("updated_at", text)
        self.assertIn("PID", text)
        self.assertIn("diagnostic", text)

    def test_worker_prompt_reads_at_most_one_document_first(self) -> None:
        text = (ROOT / "prompts" / "worker.md").read_text(encoding="utf-8")
        self.assertNotIn("First read:", text)
        first_step = re.search(r"^\s*1\.\s", text, flags=re.M)
        self.assertIsNotNone(first_step)
        preamble = text[: first_step.start()]
        docs = set(re.findall(r"(?:\.ai/|agents/)[A-Za-z0-9_./-]+\.md", preamble))
        self.assertLessEqual(len(docs), 1, f"worker.md asks for {sorted(docs)} before the first step")

    def test_capabilities_list_every_command(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        published = set(json.loads(run(workspace, "capabilities").stdout)["commands"])
        self.assertEqual(sorted(set(parser_tree()) - published), [])

    def test_version_is_consistent(self) -> None:
        from lib.core.paths import VERSION

        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), VERSION)
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [{VERSION}]", changelog)


class CodeHygieneTest(unittest.TestCase):
    def test_no_unused_imports_in_lib(self) -> None:
        problems = []
        for path in sorted((ROOT / "lib").rglob("*.py")):
            if "tests" in path.parts or path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = {}
            for node in tree.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported[(alias.asname or alias.name).split(".")[0]] = node.lineno
                elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
                    for alias in node.names:
                        imported[alias.asname or alias.name] = node.lineno
            used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            used |= {n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
            text = path.read_text(encoding="utf-8")
            for name, line in imported.items():
                if name not in used and not re.search(rf"\b{re.escape(name)}\b.*#\s*noqa", text):
                    problems.append(f"{path.relative_to(ROOT)}:{line} unused import {name}")
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
