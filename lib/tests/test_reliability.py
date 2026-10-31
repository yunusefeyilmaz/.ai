"""Lease, recovery, and Git workflow regressions in isolated workspaces."""

from __future__ import annotations

import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo")


def run(workspace: Path, *args: str, timeout: int = 12) -> subprocess.CompletedProcess[str]:
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


def git(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=workspace, check=True, capture_output=True, text=True, timeout=10
    )


class ReliabilityCase(unittest.TestCase):
    def make_workspace(self, *, with_git: bool = False) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="ai-reliability-"))
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
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        if with_git:
            git(workspace, "init", "-q", "--initial-branch=develop")
            git(workspace, "config", "user.name", "Reliability Test")
            git(workspace, "config", "user.email", "reliability@example.test")
            git(workspace, "add", "-A")
            git(workspace, "commit", "-qm", "test baseline")
            git(workspace, "branch", "master")
        return workspace

    def create_claimed_task(self, workspace: Path, agent: str = "worker") -> None:
        created = run(workspace, "task", "new", "Reliability scenario", "--no-spec")
        self.assertEqual(created.returncode, 0, created.stderr + created.stdout)
        claimed = run(workspace, "task", "claim", "0001", "--agent", agent)
        self.assertEqual(claimed.returncode, 0, claimed.stderr + claimed.stdout)


class LeaseReliabilityTest(ReliabilityCase):
    def test_concurrent_acquisition_has_exactly_one_winner(self) -> None:
        workspace = self.make_workspace()

        def acquire(agent: str) -> subprocess.CompletedProcess[str]:
            return run(
                workspace, "lock", "acquire", "docs/shared",
                "--agent", agent, "--task", "0001",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(acquire, ("writer-a", "writer-b")))

        self.assertEqual(
            sum(result.returncode == 0 for result in results), 1,
            "concurrent_acquisition: expected exactly one lease winner; "
            + " | ".join(result.stdout + result.stderr for result in results),
        )

    def test_expired_lease_can_be_taken_over(self) -> None:
        workspace = self.make_workspace()
        first = run(workspace, "lock", "acquire", "docs/shared", "--agent", "old")
        self.assertEqual(first.returncode, 0, first.stderr)
        lock_path = next((workspace / "runtime" / "locks").glob("*.lock"))
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        payload["updated_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        lock_path.write_text(json.dumps(payload), encoding="utf-8")

        takeover = run(
            workspace, "lock", "acquire", "docs/shared", "--agent", "new",
            "--force",
        )
        self.assertEqual(takeover.returncode, 0, takeover.stderr + takeover.stdout)
        self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["agent"], "new")

    def test_previous_owner_cannot_release_after_takeover(self) -> None:
        workspace = self.make_workspace()
        first = run(workspace, "lock", "acquire", "docs/shared", "--agent", "old")
        self.assertEqual(first.returncode, 0, first.stderr)
        lock_path = next((workspace / "runtime" / "locks").glob("*.lock"))
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        payload["updated_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        lock_path.write_text(json.dumps(payload), encoding="utf-8")
        takeover = run(
            workspace, "lock", "acquire", "docs/shared", "--agent", "new", "--force",
        )
        self.assertEqual(takeover.returncode, 0, takeover.stderr)

        stale_owner = run(workspace, "lock", "release", "docs/shared", "--agent", "old")
        self.assertEqual(stale_owner.returncode, 1, stale_owner.stdout + stale_owner.stderr)
        self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["agent"], "new")

    def test_recover_apply_repairs_owner_lock_drift(self) -> None:
        workspace = self.make_workspace()
        self.create_claimed_task(workspace, "stranded")
        lock_path = next((workspace / "runtime" / "locks").glob("task-0001.lock"))
        lock_path.unlink()

        recovered = run(workspace, "recover", "--apply")
        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        task = run(workspace, "task", "show", "0001")
        self.assertIn("status: todo", task.stdout)
        self.assertIn("owner: None", task.stdout)
        self.assertFalse(lock_path.exists())

    def test_task_lease_does_not_block_project_file_lease(self) -> None:
        workspace = self.make_workspace()
        self.create_claimed_task(workspace)

        project_lease = run(
            workspace, "lock", "acquire", "project", "--agent", "file-editor", "--task", "0001",
        )
        self.assertEqual(
            project_lease.returncode, 0,
            "task_namespace_is_separate: project lease was blocked by task claim: "
            + project_lease.stdout + project_lease.stderr,
        )


class GitReliabilityTest(ReliabilityCase):
    def test_dirty_product_index_blocks_task_branch_start(self) -> None:
        workspace = self.make_workspace(with_git=True)
        config_path = workspace / "config" / "workspace.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config.setdefault("git", {})["enabled"] = False  # claim must not branch by itself here
        config_path.write_text(json.dumps(config), encoding="utf-8")
        self.create_claimed_task(workspace)
        (workspace / "README.md").write_text("staged change\n", encoding="utf-8")
        git(workspace, "add", "README.md")

        result = run(
            workspace, "git", "start", "--task", "0001", "--agent", "worker", "--type", "chore",
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("product changes", result.stderr)
        self.assertEqual(git(workspace, "branch", "--show-current").stdout.strip(), "develop")

    def test_conflicting_staging_is_reported_by_git_verify(self) -> None:
        workspace = self.make_workspace(with_git=True)
        (workspace / "README.md").write_text("staged change\n", encoding="utf-8")
        git(workspace, "add", "README.md")

        result = run(workspace, "git", "verify", "--strict", "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(payload["staged"], ["README.md"])
        self.assertIn("README.md", payload["uncovered"])

    def test_failed_git_finish_keeps_task_and_integration_branches(self) -> None:
        workspace = self.make_workspace(with_git=True)
        self.create_claimed_task(workspace)
        started = run(
            workspace, "git", "start", "--task", "0001", "--agent", "worker", "--type", "chore",
        )
        self.assertEqual(started.returncode, 0, started.stderr + started.stdout)
        branch = git(workspace, "branch", "--show-current").stdout.strip()

        (workspace / "README.md").write_text("feature version\n", encoding="utf-8")
        git(workspace, "add", "README.md")
        git(workspace, "commit", "-qm", "feature change")
        review = run(workspace, "task", "review", "0001", "--agent", "worker")
        self.assertEqual(review.returncode, 0, review.stderr + review.stdout)
        released = run(workspace, "task", "release", "0001", "--agent", "worker")
        self.assertEqual(released.returncode, 0, released.stderr + released.stdout)
        git(workspace, "add", "-A")
        git(workspace, "commit", "-qm", "review metadata")

        git(workspace, "checkout", "develop")
        (workspace / "README.md").write_text("integration version\n", encoding="utf-8")
        git(workspace, "add", "README.md")
        git(workspace, "commit", "-qm", "integration change")
        git(workspace, "checkout", branch)

        result = run(workspace, "git", "finish", "--task", "0001", "--agent", "reviewer")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Merge failed", result.stderr)
        self.assertIn(branch, git(workspace, "branch", "--list").stdout)
        self.assertEqual(git(workspace, "show-ref", "--verify", f"refs/heads/{branch}").returncode, 0)
        self.assertEqual(git(workspace, "show-ref", "--verify", "refs/heads/develop").returncode, 0)


if __name__ == "__main__":
    unittest.main()
