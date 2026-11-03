"""`commit_task_metadata` may only amend the ledger paths it owns (task 0007).

The amend is the ledger follow-up of `ai git commit`: it folds the task file and
the board into the product commit that was just created. Anything else in the
index belongs to the user's own work and must never join that commit.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib.git import repo  # noqa: E402


def git(workspace: Path, *args: str) -> str:
    """Run git in the workspace and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    return result.stdout


class MetadataCommitTest(unittest.TestCase):
    """Every test builds a throw-away repository with one task file and a board."""

    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="ai-metadata-commit-"))
        self.addCleanup(shutil.rmtree, self.workspace, True)
        (self.workspace / "tasks").mkdir()
        (self.workspace / "BOARD.md").write_text("# board\n", encoding="utf-8")
        self.task = self.workspace / "tasks" / "0001-probe.md"
        self.task.write_text("---\nid: 0001\n---\n\nbody\n", encoding="utf-8")
        git(self.workspace, "init", "-q", "--initial-branch=master")
        git(self.workspace, "config", "user.name", "Metadata Test")
        git(self.workspace, "config", "user.email", "metadata@example.test")
        git(self.workspace, "add", "-A")
        git(self.workspace, "commit", "-qm", "baseline")

    def update_ledger(self) -> None:
        """What the real flow writes before it records the ledger in git."""
        self.task.write_text("---\nid: 0001\n---\n\nbody, updated\n", encoding="utf-8")
        (self.workspace / "BOARD.md").write_text("# board\n\n- 0001\n", encoding="utf-8")

    def stage(self, name: str, text: str = "user work\n") -> None:
        """Stage a file the metadata commit does not own."""
        (self.workspace / name).write_text(text, encoding="utf-8")
        git(self.workspace, "add", "--", name)

    def record(self, message: str = "", amend: bool = True):
        """Call the library directly: same code path as the CLI, no start-up cost."""
        events: list[tuple[str, dict]] = []
        stderr = io.StringIO()
        with mock.patch.object(repo, "PROJECT", str(self.workspace)), \
                mock.patch.object(repo, "BOARD_PATH", str(self.workspace / "BOARD.md")), \
                mock.patch.object(repo, "append_event", lambda name, **fields: events.append((name, fields))), \
                redirect_stderr(stderr), \
                repo.working_in(str(self.workspace)):
            result = repo.commit_task_metadata(str(self.task), message, amend=amend)
        return result, stderr.getvalue(), events

    def test_amend_folds_in_the_ledger_paths_and_nothing_else(self) -> None:
        self.update_ledger()

        result, stderr, events = self.record(amend=True)

        self.assertIsNotNone(result, stderr)
        self.assertEqual(stderr, "")
        self.assertEqual(events, [])
        # An amend replaces the last commit instead of adding one.
        self.assertEqual(git(self.workspace, "rev-list", "--count", "HEAD").strip(), "1")
        self.assertEqual(git(self.workspace, "log", "-1", "--pretty=%s").strip(), "baseline")
        committed = git(self.workspace, "show", "--name-only", "--pretty=format:", "HEAD")
        self.assertIn("tasks/0001-probe.md", committed)
        self.assertIn("BOARD.md", committed)
        self.assertEqual(git(self.workspace, "status", "--porcelain").strip(), "")

    def test_unrelated_staged_path_skips_the_amend_and_stays_staged(self) -> None:
        self.stage("scratch.txt")
        self.update_ledger()

        result, stderr, events = self.record(amend=True)

        self.assertIsNone(result)
        self.assertIn("task metadata was not amended", stderr)
        self.assertIn("scratch.txt", stderr)
        # The product commit was not rewritten, so the user's file is not in it.
        self.assertEqual(git(self.workspace, "rev-list", "--count", "HEAD").strip(), "1")
        committed = git(self.workspace, "show", "--name-only", "--pretty=format:", "HEAD")
        self.assertNotIn("scratch.txt", committed)
        # Nothing was lost: both the user's work and the ledger stay staged.
        staged = git(self.workspace, "diff", "--cached", "--name-only")
        self.assertIn("scratch.txt", staged)
        self.assertIn("tasks/0001-probe.md", staged)
        self.assertEqual([name for name, _ in events], ["git_metadata_amend_skipped"])
        self.assertEqual(events[0][1]["paths"], ["scratch.txt"])

    def test_new_commit_keeps_its_message_and_ignores_other_staged_paths(self) -> None:
        self.stage("scratch.txt")
        self.update_ledger()

        result, stderr, events = self.record("chore(task): record merge 0001", amend=False)

        self.assertIsNotNone(result, stderr)
        self.assertEqual(events, [])
        self.assertEqual(git(self.workspace, "rev-list", "--count", "HEAD").strip(), "2")
        self.assertEqual(
            git(self.workspace, "log", "-1", "--pretty=%s").strip(),
            "chore(task): record merge 0001",
        )
        # A pathspec commit records the ledger only; the user's file stays staged.
        committed = git(self.workspace, "show", "--name-only", "--pretty=format:", "HEAD")
        self.assertIn("tasks/0001-probe.md", committed)
        self.assertIn("BOARD.md", committed)
        self.assertNotIn("scratch.txt", committed)
        self.assertIn("scratch.txt", git(self.workspace, "diff", "--cached", "--name-only"))

    def test_unexpected_staged_reports_only_foreign_paths(self) -> None:
        rels = ["tasks/0001-probe.md", "BOARD.md"]

        self.assertEqual(repo.unexpected_staged(rels, rels), [])
        self.assertEqual(
            repo.unexpected_staged(
                rels, ["BOARD.md", r"tasks\0001-probe.md", "src/app.py", "src/app.py"]
            ),
            ["src/app.py"],
        )
        self.assertEqual(repo.unexpected_staged(rels, []), [])


if __name__ == "__main__":
    unittest.main()
