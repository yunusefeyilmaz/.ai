"""Workflow metrics are local, append-only, and read-only when queried."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo")


def run(workspace: Path, *args: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(workspace / "scripts" / "ai.py"), *args],
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
        ["git", *args], cwd=workspace, check=True, capture_output=True, text=True, timeout=15
    )


class MetricsCase(unittest.TestCase):
    def make_workspace(self, *, with_git: bool = False) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="ai-metrics-"))
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
            git(workspace, "config", "user.name", "Metrics Test")
            git(workspace, "config", "user.email", "metrics@example.test")
            git(workspace, "add", "-A")
            git(workspace, "commit", "-qm", "test baseline")
            git(workspace, "branch", "master")
        return workspace

    def check_ok(self, workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
        result = run(workspace, *args)
        self.assertEqual(result.returncode, 0, f"{' '.join(args)}: {result.stderr}{result.stdout}")
        return result


class WorkflowMetricsTest(MetricsCase):
    def test_empty_metrics_are_read_only(self) -> None:
        workspace = self.make_workspace()
        state = workspace / "runtime" / "state"
        shutil.rmtree(state, ignore_errors=True)

        result = self.check_ok(workspace, "metrics", "--json")
        payload = json.loads(result.stdout)

        self.assertFalse(state.exists(), "metrics must not create the runtime state tree")
        self.assertEqual(payload["events_recorded"], 0)
        self.assertEqual(payload["tasks_completed"], 0)
        self.assertIsNone(payload["median_creation_to_done_seconds"])
        self.assertIsNone(payload["median_review_to_merge_seconds"])
        self.assertEqual(payload["per_agent"], {})

    def test_task_lifecycle_events_produce_metrics_and_since_filter(self) -> None:
        workspace = self.make_workspace(with_git=True)
        self.check_ok(workspace, "task", "new", "Metrics lifecycle", "--no-spec")
        self.check_ok(workspace, "task", "claim", "0001", "--agent", "alice")
        self.check_ok(workspace, "task", "release", "0001", "--agent", "alice")
        self.check_ok(workspace, "task", "claim", "0001", "--agent", "alice")
        self.check_ok(
            workspace, "git", "start", "--task", "0001", "--agent", "alice", "--type", "feature",
        )
        self.check_ok(
            workspace, "checkpoint", "0001", "--agent", "alice", "--next", "submit for review",
        )
        self.check_ok(workspace, "resume", "0001", "--json")

        self.check_ok(workspace, "lock", "acquire", "docs/shared", "--agent", "owner")
        refused = run(workspace, "lock", "acquire", "docs/shared/file", "--agent", "blocked")
        self.assertEqual(refused.returncode, 1, refused.stderr + refused.stdout)
        self.check_ok(workspace, "lock", "release", "docs/shared", "--agent", "owner")

        (workspace / "sample.txt").write_text("local test commit\n", encoding="utf-8")
        git(workspace, "add", "sample.txt")
        git(workspace, "commit", "-qm", "sample task change")
        self.check_ok(workspace, "task", "review", "0001", "--agent", "alice")
        self.check_ok(workspace, "task", "release", "0001", "--agent", "alice")
        git(workspace, "add", "-A")
        git(workspace, "commit", "-qm", "review task metadata")
        self.check_ok(workspace, "git", "finish", "--task", "0001", "--agent", "reviewer")
        self.check_ok(workspace, "task", "done", "0001", "--agent", "reviewer")

        ledger = workspace / "runtime" / "state" / "events.jsonl"
        events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            [event["event"] for event in events],
            [
                "task_created", "task_claimed", "task_released", "task_claimed",
                "checkpoint", "resume", "lock_refused", "task_reviewed",
                "task_released", "task_merged", "task_done",
            ],
        )

        metrics = json.loads(self.check_ok(workspace, "metrics", "--json").stdout)
        self.assertEqual(metrics["events_recorded"], len(events))
        self.assertEqual(metrics["tasks_completed"], 1)
        self.assertEqual(metrics["lock_refusals"], 1)
        self.assertEqual(metrics["retries"], 1)
        self.assertEqual(metrics["resumes"], 1)
        self.assertEqual(metrics["per_agent"]["alice"], 7)

        stamps = {
            event["event"]: datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
            for event in events
            if event["event"] in ("task_created", "task_reviewed", "task_merged", "task_done")
        }
        self.assertEqual(
            metrics["median_creation_to_done_seconds"],
            (stamps["task_done"] - stamps["task_created"]).total_seconds(),
        )
        self.assertEqual(
            metrics["median_review_to_merge_seconds"],
            (stamps["task_merged"] - stamps["task_reviewed"]).total_seconds(),
        )
        created = next(event for event in events if event["event"] == "task_created")
        created_at = datetime.fromisoformat(created["timestamp"].replace("Z", "+00:00"))
        created["timestamp"] = (created_at - timedelta(days=1)).isoformat().replace("+00:00", "Z")
        ledger.write_text(
            "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
            encoding="utf-8",
        )
        since_done = stamps["task_done"].date().isoformat()
        filtered = json.loads(
            self.check_ok(workspace, "metrics", "--json", "--since", since_done).stdout
        )
        self.assertEqual(filtered["tasks_completed"], 1)
        self.assertEqual(
            filtered["median_creation_to_done_seconds"],
            (stamps["task_done"] - created_at + timedelta(days=1)).total_seconds(),
        )
        future = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
        filtered = json.loads(self.check_ok(workspace, "metrics", "--json", "--since", future).stdout)
        self.assertEqual(filtered["events_recorded"], 0)
        self.assertEqual(filtered["tasks_completed"], 0)
        self.assertIsNone(filtered["median_creation_to_done_seconds"])
        self.assertEqual(filtered["per_agent"], {})

    def test_daily_rotation_preserves_events_for_metrics(self) -> None:
        workspace = self.make_workspace()
        self.check_ok(workspace, "task", "new", "Rotation probe", "--no-spec")
        ledger = workspace / "runtime" / "state" / "events.jsonl"
        first = json.loads(ledger.read_text(encoding="utf-8").strip())
        first["timestamp"] = "2000-01-01T00:00:00Z"
        ledger.write_text(json.dumps(first) + "\n", encoding="utf-8")

        self.check_ok(workspace, "lock", "acquire", "docs/shared", "--agent", "owner")
        refused = run(workspace, "lock", "acquire", "docs/shared/file", "--agent", "blocked")
        self.assertEqual(refused.returncode, 1)

        archive = workspace / "runtime" / "state" / "events-2000-01-01.jsonl"
        self.assertTrue(archive.is_file())
        metrics = json.loads(self.check_ok(workspace, "metrics", "--json").stdout)
        self.assertEqual(metrics["events_recorded"], 2)
        self.assertEqual(metrics["lock_refusals"], 1)


if __name__ == "__main__":
    unittest.main()
