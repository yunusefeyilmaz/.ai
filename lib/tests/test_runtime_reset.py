from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT))

from lib.runtime import reset as runtime_reset


class ResetDecisionsDirGuardTest(unittest.TestCase):
    def test_allows_workspace_paths_with_symlinked_ancestors(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ai-reset-workspace-") as temp:
            root = Path(temp)
            real_workspace = root / "real-workspace"
            decisions = real_workspace / "docs" / "decisions"
            decisions.mkdir(parents=True)

            alias_workspace = root / "alias-workspace"
            try:
                alias_workspace.symlink_to(real_workspace, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation not supported in this environment")

            old_workspace = runtime_reset.WORKSPACE
            old_decisions = runtime_reset.DECISIONS_DIR
            runtime_reset.WORKSPACE = str(alias_workspace)
            runtime_reset.DECISIONS_DIR = str(alias_workspace / "docs" / "decisions")
            try:
                self.assertIsNone(runtime_reset.reset_decisions_dir_error())
            finally:
                runtime_reset.WORKSPACE = old_workspace
                runtime_reset.DECISIONS_DIR = old_decisions

    def test_rejects_decisions_directory_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ai-reset-workspace-") as temp:
            root = Path(temp)
            workspace = root / "workspace"
            outside_docs = root / "outside-docs"
            (workspace / "docs").mkdir(parents=True)
            outside_decisions = outside_docs / "decisions"
            outside_decisions.mkdir(parents=True)

            docs_link = workspace / "docs"
            os.rmdir(docs_link)
            try:
                docs_link.symlink_to(outside_docs, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation not supported in this environment")

            old_workspace = runtime_reset.WORKSPACE
            old_decisions = runtime_reset.DECISIONS_DIR
            runtime_reset.WORKSPACE = str(workspace)
            runtime_reset.DECISIONS_DIR = str(workspace / "docs" / "decisions")
            try:
                self.assertEqual(
                    runtime_reset.reset_decisions_dir_error(),
                    "Refusing to reset decision records outside docs/decisions.",
                )
            finally:
                runtime_reset.WORKSPACE = old_workspace
                runtime_reset.DECISIONS_DIR = old_decisions


if __name__ == "__main__":
    unittest.main()
