"""A claim is atomic: a failed task branch releases the task and its locks."""

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


class ClaimRollbackCase(unittest.TestCase):
    def make_workspace(self, with_develop: bool) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="ai-claim-rollback-"))
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

        git(workspace, "init", "-q", "--initial-branch=master")
        git(workspace, "config", "user.name", "Claim Rollback Test")
        git(workspace, "config", "user.email", "claim@example.test")
        git(workspace, "add", "-A")
        git(workspace, "commit", "-qm", "test baseline")
        if with_develop:
            git(workspace, "branch", "develop")
        return workspace

    def create_task(self, workspace: Path) -> None:
        created = run(
            workspace, "task", "new", "Rollback scenario",
            "--no-spec", "--allow", "src/app.py",
        )
        self.assertEqual(created.returncode, 0, created.stderr + created.stdout)

    def test_dirty_product_tree_rolls_the_claim_back(self) -> None:
        workspace = self.make_workspace(with_develop=True)
        self.create_task(workspace)
        (workspace / "scratch.txt").write_text("uncommitted work\n", encoding="utf-8")

        claimed = run(workspace, "task", "claim", "0001", "--agent", "alice")
        self.assertEqual(claimed.returncode, 1, claimed.stdout + claimed.stderr)
        self.assertIn("rolled back", claimed.stderr)
        self.assertIn("ai task claim 0001 --agent alice", claimed.stderr)

        shown = run(workspace, "task", "show", "0001").stdout
        self.assertIn("status: todo", shown)
        self.assertIn("owner: None", shown)
        self.assertIn("lock: None", shown)

        locks = run(workspace, "lock", "status").stdout
        self.assertIn("No locks held.", locks)

        history = run(workspace, "history", "0001").stdout
        self.assertIn("claim rolled back", history)
        self.assertIn("the task branch could not start", history)

        events = (workspace / "runtime" / "state" / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn("claim_rolled_back", events)
        self.assertNotIn("Traceback", claimed.stderr)

    def test_missing_integration_branch_keeps_the_claim_for_setup(self) -> None:
        # `ai start` claims before `ai git setup`: a missing Gitflow base is a
        # setup step, not a failed branch, so the claim must survive.
        workspace = self.make_workspace(with_develop=False)
        self.create_task(workspace)

        claimed = run(workspace, "task", "claim", "0001", "--agent", "alice")
        self.assertEqual(claimed.returncode, 0, claimed.stdout + claimed.stderr)
        self.assertIn("integration branch 'develop' is missing", claimed.stdout)
        self.assertIn("status: in_progress", run(workspace, "task", "show", "0001").stdout)

    def test_successful_claim_starts_the_branch_and_prints_once(self) -> None:
        workspace = self.make_workspace(with_develop=True)
        self.create_task(workspace)

        claimed = run(workspace, "task", "claim", "0001", "--agent", "alice")
        self.assertEqual(claimed.returncode, 0, claimed.stdout + claimed.stderr)
        self.assertEqual(claimed.stdout.count("Claimed 0001 for alice."), 1)

        shown = run(workspace, "task", "show", "0001").stdout
        self.assertIn("status: in_progress", shown)
        self.assertIn("owner: alice", shown)
        branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=workspace,
            capture_output=True, text=True, check=True, timeout=20,
        ).stdout.strip()
        self.assertTrue(branch.startswith("feature/0001-"), branch)


if __name__ == "__main__":
    unittest.main()
