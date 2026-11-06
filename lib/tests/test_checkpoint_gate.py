"""Delivery needs a checkpoint when a claim is old, `done` leaves a clean tree.

A long-running claim must hand over recoverable state, but a task that is still
young must not be forced into busywork. `ai task done` is the last ledger write
of a task's life, so it records the archived task, shipped spec and board in
git instead of leaving them dirty for the next agent.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from _workspace import GitSpec  # noqa: E402
from _workspace import make_workspace as build_workspace  # noqa: E402


def run(workspace: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
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
        ["git", *args], cwd=workspace, check=True, capture_output=True, text=True, timeout=30
    )


def zero_warn(config: dict) -> None:
    """Make any real claim old enough to require a checkpoint (stable cache key)."""
    config.setdefault("handoff", {})["warnAfterMinutes"] = 0


class CheckpointGateCase(unittest.TestCase):
    def make_workspace(self, configure=None) -> Path:
        spec = GitSpec("develop", "Checkpoint Gate", "checkpoint@example.test", ("master",))
        return build_workspace(self, "ai-checkpoint-gate-", git=spec, configure=configure)

    def claimed(self, workspace: Path, agent: str = "alice") -> None:
        created = run(workspace, "task", "new", "Checkpoint gate")
        self.assertEqual(created.returncode, 0, created.stderr + created.stdout)
        claim = run(workspace, "task", "claim", "0001", "--agent", agent)
        self.assertEqual(claim.returncode, 0, claim.stderr + claim.stdout)

    def commit_all(self, workspace: Path, message: str) -> None:
        git(workspace, "add", "-A")
        git(workspace, "commit", "-qm", message)


class RequiredCheckpointTest(CheckpointGateCase):
    def test_old_claim_is_refused_until_a_checkpoint_exists(self) -> None:
        workspace = self.make_workspace(zero_warn)
        self.claimed(workspace)
        self.commit_all(workspace, "feat: work")

        refused = run(workspace, "task", "review", "0001", "--agent", "alice")

        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("without a checkpoint", refused.stderr)
        self.assertIn("ai checkpoint 0001", refused.stderr)
        self.assertIn("--next", refused.stderr)

        saved = run(workspace, "checkpoint", "0001", "--agent", "alice", "--next", "deliver")
        self.assertEqual(saved.returncode, 0, saved.stderr + saved.stdout)
        reviewed = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr + reviewed.stdout)

    def test_fresh_claim_delivers_without_a_checkpoint(self) -> None:
        workspace = self.make_workspace()
        self.claimed(workspace)
        self.commit_all(workspace, "feat: work")

        reviewed = run(workspace, "task", "review", "0001", "--agent", "alice")

        self.assertEqual(reviewed.returncode, 0, reviewed.stderr + reviewed.stdout)
        self.assertNotIn("without a checkpoint", reviewed.stderr)


class CheckpointContentTest(CheckpointGateCase):
    def test_checkpoint_records_status_branch_head_and_next_step(self) -> None:
        workspace = self.make_workspace()
        self.claimed(workspace)

        made = run(workspace, "checkpoint", "0001", "--agent", "alice")
        self.assertEqual(made.returncode, 0, made.stderr + made.stdout)

        text = (workspace / "runtime" / "state" / "checkpoints" / "0001.md").read_text(
            encoding="utf-8"
        )
        head = git(workspace, "rev-parse", "--short=8", "HEAD").stdout.strip()

        self.assertNotIn("<!--", text, "unresolved template placeholders must be replaced")
        self.assertIn("in_progress", text)
        self.assertIn("branch feature/0001-", text)
        self.assertIn(head, text)
        self.assertIn("## Next steps", text)
        self.assertIn("Continue task 0001", text)


class DoneLedgerCommitTest(CheckpointGateCase):
    def test_done_commits_the_archived_task_spec_and_board(self) -> None:
        workspace = self.make_workspace()
        self.claimed(workspace)
        (workspace / "sample.txt").write_text("work\n", encoding="utf-8")
        self.commit_all(workspace, "feat: work")

        reviewed = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr + reviewed.stdout)
        # The producer records the review ledger, then the reviewer merges.
        self.commit_all(workspace, "chore: record review")
        merged = run(workspace, "git", "finish", "--task", "0001", "--agent", "bob")
        self.assertEqual(merged.returncode, 0, merged.stderr + merged.stdout)

        done = run(workspace, "task", "done", "0001", "--agent", "bob")
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)

        status = git(workspace, "status", "--porcelain").stdout.strip()
        self.assertEqual(status, "", f"working tree must be clean after done: {status}")
        subject = git(workspace, "log", "-1", "--pretty=%s").stdout.strip()
        self.assertEqual(subject, "chore(task): record done 0001")
        committed = git(workspace, "show", "--name-only", "--pretty=format:", "HEAD").stdout
        self.assertIn("tasks/done/0001-", committed)
        self.assertIn("specs/done/0001-", committed)
        self.assertIn("tasks/BOARD.md", committed)
        self.assertEqual(list((workspace / "tasks" / "active").glob("0001-*.md")), [])


if __name__ == "__main__":
    unittest.main()
