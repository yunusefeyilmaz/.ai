"""Lock ownership: TTL-only staleness, idempotent re-claim, release guard.

A task claim outlives the CLI process that created it, so ownership - not PID
liveness - decides whether a lease is stale. Re-claiming your own task renews
the lease instead of failing, and releasing someone else's lease needs an
explicit --force.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT))

from test_start import WorkspaceCase, run  # noqa: E402

# Longer than the old 30s PID-liveness window, far below the 3600s TTL.
PAST_PID_WINDOW_SECONDS = 90


def stamp(seconds_ago: int = 0) -> str:
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class LockOwnershipTest(WorkspaceCase):
    def task_workspace(self) -> Path:
        workspace = self.make_workspace(git_repo=False)
        created = run(workspace, "task", "new", "Lock ownership")
        self.assertEqual(created.returncode, 0, created.stderr)
        return workspace

    def lock_file(self, workspace: Path, resource: str) -> Path:
        files = list((workspace / "runtime" / "locks").glob(f"*{resource}*.lock"))
        self.assertEqual(len(files), 1, [item.name for item in files])
        return files[0]

    def lock_files(self, workspace: Path, resource: str) -> list[Path]:
        return list((workspace / "runtime" / "locks").glob(f"*{resource}*.lock"))

    def read_lock(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def age_lock(self, path: Path, seconds: int = PAST_PID_WINDOW_SECONDS) -> None:
        payload = self.read_lock(path)
        payload["started_at"] = stamp(seconds)
        payload["updated_at"] = stamp(seconds)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def task_text(self, workspace: Path) -> str:
        files = list((workspace / "tasks" / "active").glob("0001-*.md"))
        self.assertEqual(len(files), 1, [item.name for item in files])
        return files[0].read_text(encoding="utf-8")

    def events(self, workspace: Path) -> str:
        path = workspace / "runtime" / "state" / "events.jsonl"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_a_live_task_claim_survives_the_old_pid_window(self) -> None:
        workspace = self.task_workspace()
        claimed = run(workspace, "task", "claim", "0001", "--agent", "alice")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        self.age_lock(self.lock_file(workspace, "task-0001"))
        before = self.task_text(workspace)

        stolen = run(workspace, "task", "claim", "0001", "--agent", "bob")

        self.assertEqual(stolen.returncode, 1, stolen.stdout + stolen.stderr)
        self.assertIn("alice", stolen.stderr)
        self.assertEqual(self.task_text(workspace), before, "a refused claim must not touch the task")
        self.assertIn("owner: alice", before)
        self.assertNotIn("branch:", before)
        self.assertEqual(self.read_lock(self.lock_file(workspace, "task-0001"))["agent"], "alice")

    def test_doctor_does_not_report_a_live_claim_as_stale(self) -> None:
        workspace = self.task_workspace()
        claimed = run(workspace, "task", "claim", "0001", "--agent", "alice")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        self.age_lock(self.lock_file(workspace, "task-0001"))

        result = run(workspace, "doctor", "--json")

        payload = json.loads(result.stdout)
        messages = [finding["message"] for finding in payload["check"]["findings"]]
        self.assertFalse(
            [message for message in messages if message.startswith("stale lock")],
            messages,
        )

    def test_recover_proposes_nothing_for_a_live_claim(self) -> None:
        workspace = self.task_workspace()
        claimed = run(workspace, "task", "claim", "0001", "--agent", "alice")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        self.age_lock(self.lock_file(workspace, "task-0001"))

        result = run(workspace, "recover", "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        actions = json.loads(result.stdout)["actions"]
        self.assertFalse([action for action in actions if "stale lock" in action], actions)
        self.assertFalse([action for action in actions if "stale owner" in action], actions)

    def test_reclaiming_your_own_task_renews_the_lease_in_place(self) -> None:
        workspace = self.task_workspace()
        claimed = run(workspace, "task", "claim", "0001", "--agent", "alice")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        lock = self.lock_file(workspace, "task-0001")
        self.age_lock(lock)
        aged = self.read_lock(lock)

        again = run(workspace, "task", "claim", "0001", "--agent", "alice")

        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(
            len(self.lock_files(workspace, "task-0001")), 1, "a renewal must not duplicate the lease"
        )
        renewed = self.read_lock(lock)
        self.assertGreater(renewed["updated_at"], aged["updated_at"])
        self.assertEqual(renewed["started_at"], aged["started_at"], "the original claim time is history")
        self.assertGreater(renewed["expires_at"], renewed["updated_at"])
        self.assertNotIn("lock_replaced_stale", self.events(workspace))
        self.assertIn("owner: alice", self.task_text(workspace))

    def test_release_without_agent_names_the_owner_and_refuses(self) -> None:
        workspace = self.task_workspace()
        self.assertEqual(
            run(workspace, "lock", "acquire", "task-0001", "--agent", "alice", "--task", "0001").returncode,
            0,
        )

        anonymous = run(workspace, "lock", "release", "task-0001")

        self.assertEqual(anonymous.returncode, 1)
        self.assertIn("alice", anonymous.stderr)
        self.assertTrue(self.lock_file(workspace, "task-0001").is_file())

    def test_release_by_another_agent_refuses_and_the_owner_succeeds(self) -> None:
        workspace = self.task_workspace()
        self.assertEqual(
            run(workspace, "lock", "acquire", "task-0001", "--agent", "alice", "--task", "0001").returncode,
            0,
        )

        wrong_agent = run(workspace, "lock", "release", "task-0001", "--agent", "bob")
        self.assertEqual(wrong_agent.returncode, 1)
        self.assertIn("alice", wrong_agent.stderr)
        self.assertTrue(self.lock_file(workspace, "task-0001").is_file())

        me = run(workspace, "lock", "release", "task-0001", "--agent", "alice")
        self.assertEqual(me.returncode, 0, me.stderr)
        self.assertEqual(self.lock_files(workspace, "task-0001"), [])

    def test_force_release_still_works_without_an_agent(self) -> None:
        workspace = self.task_workspace()
        self.assertEqual(
            run(workspace, "lock", "acquire", "task-0001", "--agent", "alice", "--task", "0001").returncode,
            0,
        )

        forced = run(workspace, "lock", "release", "task-0001", "--force")

        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertEqual(self.lock_files(workspace, "task-0001"), [])


if __name__ == "__main__":
    unittest.main()
