"""`ai task done` must inherit a stale task lock, not refuse forever.

A crashed reviewer leaves `task-<id>.lock` behind. `ai task claim` and
`ai recover` already treat a stale lease as gone; `ai task done` read the file
raw, so a finished task stayed in review until a human deleted the lock.
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


def stamp(minutes_ago: int) -> str:
    moment = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DoneStaleLockTest(WorkspaceCase):
    def prepare(self) -> Path:
        """A task in review that bob may archive (alice produced it)."""
        workspace = self.make_workspace(git_repo=False)
        run(workspace, "task", "new", "Finished work")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        review = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(review.returncode, 0, review.stderr)
        run(workspace, "task", "release", "0001", "--agent", "alice")
        self.assertEqual(run(workspace, "lock", "status").stdout.strip(), "No locks held.")
        return workspace

    def lock_file(self, workspace: Path) -> Path:
        """The real lease file: `lock_path` suffixes the name with a digest."""
        files = list((workspace / "runtime" / "locks").glob("*task-0001*.lock"))
        self.assertEqual(len(files), 1, [item.name for item in files])
        return files[0]

    def take_lock(self, workspace: Path, agent: str = "ghost", minutes_ago: int = 0) -> Path:
        """A genuine lease from the CLI, optionally aged past the staleness TTL."""
        acquired = run(
            workspace, "lock", "acquire", "task-0001", "--agent", agent, "--task", "0001"
        )
        self.assertEqual(acquired.returncode, 0, acquired.stderr)
        path = self.lock_file(workspace)
        if minutes_ago:
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["started_at"] = stamp(minutes_ago)
            payload["updated_at"] = stamp(minutes_ago)
            path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def events(self, workspace: Path) -> str:
        return (workspace / "runtime" / "state" / "events.jsonl").read_text(encoding="utf-8")

    def status(self, workspace: Path) -> str:
        return run(workspace, "task", "show", "0001").stdout

    def test_a_stale_lock_is_inherited_and_the_task_is_archived(self) -> None:
        workspace = self.prepare()
        self.take_lock(workspace, agent="ghost", minutes_ago=180)

        done = run(workspace, "task", "done", "0001", "--agent", "bob")

        self.assertEqual(done.returncode, 0, done.stderr)
        archived = list((workspace / "tasks" / "done").glob("0001-*.md"))
        self.assertEqual(len(archived), 1)
        self.assertEqual(list((workspace / "tasks" / "active").glob("0001-*.md")), [])
        self.assertNotIn("locked by", done.stderr)

    def test_the_takeover_is_recorded_in_the_event_log(self) -> None:
        workspace = self.prepare()
        self.take_lock(workspace, agent="ghost", minutes_ago=180)

        self.assertEqual(run(workspace, "task", "done", "0001", "--agent", "bob").returncode, 0)

        events = self.events(workspace)
        self.assertIn("lock_replaced_stale", events)
        self.assertIn("ghost", events)

    def test_a_live_lock_from_another_agent_is_still_refused(self) -> None:
        workspace = self.prepare()
        self.take_lock(workspace, agent="ghost", minutes_ago=0)

        done = run(workspace, "task", "done", "0001", "--agent", "bob")

        self.assertEqual(done.returncode, 1)
        self.assertIn("locked by ghost", done.stderr)
        self.assertIn("status: review", self.status(workspace))
        self.assertNotIn("lock_replaced_stale", self.events(workspace))

    def test_a_corrupt_lock_still_fails_closed(self) -> None:
        workspace = self.prepare()
        lock = self.take_lock(workspace, agent="ghost", minutes_ago=0)
        lock.write_text("{not json", encoding="utf-8")

        done = run(workspace, "task", "done", "0001", "--agent", "bob")

        self.assertEqual(done.returncode, 1)
        self.assertIn("corrupt task lock", done.stderr)
        self.assertIn("ai lock release task-0001 --force", done.stderr)
        self.assertIn("status: review", self.status(workspace))
        self.assertTrue(lock.is_file(), "a damaged lease must never be removed silently")

    def test_our_own_live_lock_needs_no_takeover(self) -> None:
        workspace = self.prepare()
        self.take_lock(workspace, agent="bob", minutes_ago=0)

        done = run(workspace, "task", "done", "0001", "--agent", "bob")

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("lock_replaced_stale", self.events(workspace))


if __name__ == "__main__":
    unittest.main()
