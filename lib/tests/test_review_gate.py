"""Review is a Git gate: correct branch, clean tree, evidence on HEAD."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COPY_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", ".mypy_cache", ".ruff_cache", "*.pyc", "*.pyo",
)

sys.path.insert(0, str(ROOT))

from lib.git import repo


def run(workspace: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(workspace / "ai.py"), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )


def git(workspace: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=workspace, check=True, capture_output=True, text=True, timeout=20
    )


class ReviewGateCase(unittest.TestCase):
    def make_workspace(self, git_repo: bool = True) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="ai-review-gate-"))
        self.addCleanup(shutil.rmtree, temp, True)
        workspace = temp / "project"
        shutil.copytree(ROOT, workspace, ignore=COPY_IGNORE)

        for relative in ("tasks/active", "tasks/done", "specs/active", "specs/done"):
            folder = workspace / relative
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True)
        for relative in ("runtime/locks", "runtime/state", "runtime/artifacts", "runtime/logs"):
            shutil.rmtree(workspace / relative, ignore_errors=True)
        (workspace / "tasks" / "BOARD.md").write_text("# Task board\n", encoding="utf-8")

        config_path = workspace / "config" / "workspace.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["checks"] = []
        config.setdefault("workflow", {})["chiefOnlyTasks"] = False
        config["workflow"]["requireSpec"] = False
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        if git_repo:
            git(workspace, "init", "-q", "--initial-branch=develop")
            git(workspace, "config", "user.name", "Review Gate Test")
            git(workspace, "config", "user.email", "review@example.test")
            git(workspace, "add", "-A")
            git(workspace, "commit", "-qm", "test baseline")
            git(workspace, "branch", "master")
        return workspace

    def claimed(self, workspace: Path, agent: str = "alice") -> None:
        created = run(workspace, "task", "new", "Review gate", "--no-spec")
        self.assertEqual(created.returncode, 0, created.stderr + created.stdout)
        claimed = run(workspace, "task", "claim", "0001", "--agent", agent)
        self.assertEqual(claimed.returncode, 0, claimed.stderr + claimed.stdout)

    def commit_all(self, workspace: Path, message: str) -> None:
        git(workspace, "add", "-A")
        git(workspace, "commit", "-qm", message)


class PorcelainParseTest(unittest.TestCase):
    def test_rename_consumes_the_old_path(self) -> None:
        entries = repo.parse_porcelain_z("R  new/name.txt\0old/name.txt\0")
        self.assertEqual(entries, [("R ", "new/name.txt")])

    def test_copy_consumes_the_old_path(self) -> None:
        entries = repo.parse_porcelain_z("C  copy.txt\0source.txt\0")
        self.assertEqual(entries, [("C ", "copy.txt")])

    def test_delete_modify_and_untracked_are_preserved(self) -> None:
        payload = " D gone.txt\0 M changed.txt\0?? new.txt\0"
        self.assertEqual(
            repo.parse_porcelain_z(payload),
            [(" D", "gone.txt"), (" M", "changed.txt"), ("??", "new.txt")],
        )

    def test_real_staged_rename_has_no_phantom_dirty_path(self) -> None:
        temp = Path(tempfile.mkdtemp(prefix="ai-porcelain-"))
        self.addCleanup(shutil.rmtree, temp, True)
        git(temp, "init", "-q")
        git(temp, "config", "user.name", "Porcelain Test")
        git(temp, "config", "user.email", "porcelain@example.test")
        (temp / "old.txt").write_text("one\n", encoding="utf-8")
        git(temp, "add", "-A")
        git(temp, "commit", "-qm", "baseline")
        git(temp, "mv", "old.txt", "new.txt")

        with repo.working_in(str(temp)):
            state = repo.git_state()

        self.assertEqual(state["dirty"], ["new.txt"])
        self.assertEqual(state["staged"], ["new.txt"])


class ReviewGateTest(ReviewGateCase):
    def test_clean_task_branch_passes(self) -> None:
        workspace = self.make_workspace()
        self.claimed(workspace)
        self.commit_all(workspace, "feat: work")

        reviewed = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr + reviewed.stdout)

    def test_wrong_branch_is_refused(self) -> None:
        workspace = self.make_workspace()
        self.claimed(workspace)
        self.commit_all(workspace, "feat: work")
        git(workspace, "checkout", "-b", "other")

        refused = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("belongs to branch", refused.stderr)
        self.assertIn("git checkout", refused.stderr)

    def test_dirty_product_tree_is_refused(self) -> None:
        workspace = self.make_workspace()
        self.claimed(workspace)
        self.commit_all(workspace, "feat: work")
        (workspace / "src").mkdir(exist_ok=True)
        (workspace / "src" / "dirty.py").write_text("pass\n", encoding="utf-8")

        refused = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("uncommitted product changes", refused.stderr)
        # Porcelain collapses an untracked directory to its leading path.
        self.assertIn("src/", refused.stderr)
        self.assertIn("ai git commit", refused.stderr)

    def test_evidence_from_another_head_is_refused(self) -> None:
        workspace = self.make_workspace()
        self.claimed(workspace)
        self.commit_all(workspace, "feat: work")
        checked = run(workspace, "check", "--task", "0001", "--agent", "alice")
        self.assertEqual(checked.returncode, 0, checked.stderr + checked.stdout)

        (workspace / "README.md").write_text("moved on\n", encoding="utf-8")
        self.commit_all(workspace, "fix: move on")

        refused = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("evidence belongs to", refused.stderr)
        self.assertIn("ai check --task 0001", refused.stderr)

        rechecked = run(workspace, "check", "--task", "0001", "--agent", "alice")
        self.assertEqual(rechecked.returncode, 0, rechecked.stderr + rechecked.stdout)
        reviewed = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr + reviewed.stdout)

    def test_workspace_without_git_still_reviews(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.claimed(workspace)

        reviewed = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr + reviewed.stdout)


if __name__ == "__main__":
    unittest.main()
