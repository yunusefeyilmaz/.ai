"""Regressions for the audit fixes: locking, IDs, timestamps and archiving.

Each CLI test builds its own temp workspace, the same way `test_reliability`
does, so the suite stays independent and parallel-safe.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo")

sys.path.insert(0, str(ROOT))


def run(workspace: Path, *args: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
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


class CliRegressionCase(unittest.TestCase):
    def make_workspace(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="ai-regressions-"))
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
        return workspace

    def lock_files(self, workspace: Path) -> list[Path]:
        return sorted((workspace / "runtime" / "locks").glob("*.lock"))

    def event_text(self, workspace: Path) -> str:
        patterns = ["events*.jsonl", "*.jsonl"]
        paths: set[Path] = set()
        for pattern in patterns:
            paths.update((workspace / "runtime" / "state").rglob(pattern))
        return "".join(path.read_text(encoding="utf-8") for path in sorted(paths))

    def create_claimed_task(self, workspace: Path, agent: str = "worker") -> None:
        created = run(workspace, "task", "new", "Regression scenario", "--no-spec")
        self.assertEqual(created.returncode, 0, created.stderr + created.stdout)
        claimed = run(workspace, "task", "claim", "0001", "--agent", agent)
        self.assertEqual(claimed.returncode, 0, claimed.stderr + claimed.stdout)


class LockRegressionTest(CliRegressionCase):
    def test_corrupt_lock_fails_closed_and_force_leaves_a_trail(self) -> None:
        workspace = self.make_workspace()
        first = run(workspace, "lock", "acquire", "docs/shared", "--agent", "alice")
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        lock_file = self.lock_files(workspace)[0]
        lock_file.write_text('{"resource": "docs/shared", ', encoding="utf-8")

        blocked = run(workspace, "lock", "acquire", "docs/other", "--agent", "bob")
        self.assertEqual(
            blocked.returncode, 1,
            "a corrupt lease must fail closed, not read as free: "
            + blocked.stdout + blocked.stderr,
        )

        forced = run(workspace, "lock", "acquire", "docs/shared", "--agent", "bob", "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr + forced.stdout)
        payload = json.loads(lock_file.read_text(encoding="utf-8"))
        self.assertEqual(payload["agent"], "bob")
        self.assertIn("lock_forced", self.event_text(workspace))

    def test_forced_takeover_of_a_live_lease_is_recorded(self) -> None:
        workspace = self.make_workspace()
        self.assertEqual(run(workspace, "lock", "acquire", "src/x.py", "--agent", "alice").returncode, 0)
        forced = run(workspace, "lock", "acquire", "src/x.py", "--agent", "bob", "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr + forced.stdout)
        events = self.event_text(workspace)
        self.assertIn("lock_forced", events)
        self.assertIn("alice", events)

    def test_stale_lease_is_replaced_without_force(self) -> None:
        workspace = self.make_workspace()
        self.assertEqual(run(workspace, "lock", "acquire", "docs/shared", "--agent", "old").returncode, 0)
        lock_file = self.lock_files(workspace)[0]
        payload = json.loads(lock_file.read_text(encoding="utf-8"))
        payload["updated_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        lock_file.write_text(json.dumps(payload), encoding="utf-8")

        takeover = run(workspace, "lock", "acquire", "docs/shared", "--agent", "new")
        self.assertEqual(takeover.returncode, 0, takeover.stderr + takeover.stdout)
        self.assertEqual(json.loads(lock_file.read_text(encoding="utf-8"))["agent"], "new")
        self.assertIn("lock_replaced_stale", self.event_text(workspace))

    def test_traversal_and_absolute_resources_are_refused(self) -> None:
        workspace = self.make_workspace()
        for resource in ("../outside", "/etc/passwd", "C:/Windows/system.ini"):
            result = run(workspace, "lock", "acquire", resource, "--agent", "mallory")
            self.assertEqual(
                result.returncode, 1,
                f"{resource!r} must not be a valid lease: " + result.stdout + result.stderr,
            )
            self.assertIn("lock resource", result.stderr.lower())
            self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.lock_files(workspace), [])

    def test_naive_timestamp_does_not_crash_lock_status(self) -> None:
        workspace = self.make_workspace()
        self.assertEqual(run(workspace, "lock", "acquire", "docs/shared", "--agent", "alice").returncode, 0)
        lock_file = self.lock_files(workspace)[0]
        payload = json.loads(lock_file.read_text(encoding="utf-8"))
        payload["updated_at"] = "2020-01-01T00:00:00"  # offset-naive, hand-edited
        payload["started_at"] = "2020-01-01T00:00:00"
        lock_file.write_text(json.dumps(payload), encoding="utf-8")

        status = run(workspace, "lock", "status", "--json")
        self.assertEqual(status.returncode, 0, status.stderr + status.stdout)
        self.assertEqual(json.loads(status.stdout)[0]["state"], "stale")

    def test_legacy_mutex_directory_from_a_crash_is_recovered(self) -> None:
        workspace = self.make_workspace()
        mutex = workspace / "runtime" / "locks" / ".registry.mutex"
        mutex.mkdir(parents=True)
        old = time.time() - 600
        os.utime(mutex, (old, old))

        result = run(workspace, "lock", "acquire", "docs/shared", "--agent", "alice", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(mutex.is_dir(), "the stale directory mutex must be upgraded")


class SetupGuidanceRegressionTest(CliRegressionCase):
    def test_fresh_project_now_prints_the_questions_inline(self) -> None:
        workspace = self.make_workspace()
        result = run(workspace, "now", "--role", "chief")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("NEXT  ai setup", result.stdout)
        self.assertIn("ask the user:", result.stdout)
        self.assertIn("ai setup --set", result.stdout)
        self.assertIn('--check "tests=<command>"', result.stdout)


class TaskRegressionTest(CliRegressionCase):
    def test_non_numeric_task_id_is_a_clean_error(self) -> None:
        workspace = self.make_workspace()
        for task_id in ("abc", "T-abc", "../../etc/passwd"):
            result = run(workspace, "task", "show", task_id)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertIn("No task with id", result.stderr)

    def test_done_never_overwrites_an_existing_archived_task(self) -> None:
        workspace = self.make_workspace()
        self.create_claimed_task(workspace)
        active = next((workspace / "tasks" / "active").glob("0001-*.md"))
        archived = workspace / "tasks" / "done" / active.name
        archived.write_text("sentinel: keep me\n", encoding="utf-8")

        result = run(
            workspace, "task", "done", "0001", "--agent", "reviewer", "--force",
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("already exists", result.stderr)
        self.assertEqual(archived.read_text(encoding="utf-8"), "sentinel: keep me\n")
        self.assertTrue(active.exists(), "the active task must stay in place")


class UnitRegressionTest(unittest.TestCase):
    def test_normalize_id_is_strict(self) -> None:
        from lib.core.fsio import normalize_id

        self.assertEqual(normalize_id("7"), "0007")
        self.assertEqual(normalize_id("T-42"), "0042")
        self.assertEqual(normalize_id("task-0003"), "0003")
        for bad in ("", "abc", "1/2", "T-", "../1", "1234567890"):
            with self.assertRaises(ValueError, msg=bad):
                normalize_id(bad)

    def test_read_json_checked_distinguishes_missing_from_corrupt(self) -> None:
        from lib.core.fsio import CorruptStateError, read_json_checked

        temp = Path(tempfile.mkdtemp(prefix="ai-regressions-"))
        self.addCleanup(shutil.rmtree, temp, True)
        missing = temp / "missing.json"
        corrupt = temp / "broken.json"
        corrupt.write_text("{not json", encoding="utf-8")

        self.assertIsNone(read_json_checked(str(missing)))
        with self.assertRaises(CorruptStateError):
            read_json_checked(str(corrupt))

    def test_parse_iso_always_returns_an_aware_datetime(self) -> None:
        from lib.core.timeutil import parse_iso

        for text in ("2020-01-01T00:00:00", "2020-01-01T00:00:00Z", "2020-01-01T03:00:00+03:00"):
            self.assertIsNotNone(parse_iso(text).tzinfo, text)

    def test_discard_spec_path_survives_an_invalid_spec_id(self) -> None:
        from unittest import mock

        from lib.tasks import discard

        temp = Path(tempfile.mkdtemp(prefix="ai-regressions-"))
        self.addCleanup(shutil.rmtree, temp, True)
        active = temp / "specs" / "active"
        done = temp / "specs" / "done"
        active.mkdir(parents=True)
        done.mkdir(parents=True)
        spec = active / "0001-regression.md"
        spec.write_text("---\ntask: abc\n---\n", encoding="utf-8")

        meta = {"id": "0001", "spec": "specs/active/0001-regression.md"}
        with mock.patch.object(discard, "WORKSPACE", str(temp)), \
                mock.patch.object(discard, "SPECS_ACTIVE_DIR", str(active)), \
                mock.patch.object(discard, "SPECS_DONE_DIR", str(done)):
            path, error = discard.task_discard_spec_path(meta, "0001")

        self.assertIsNone(path)
        self.assertIn("does not identify task 0001", error or "")

    def test_failed_metadata_commit_is_reported_not_swallowed(self) -> None:
        from unittest import mock

        from lib.git import repo

        temp = Path(tempfile.mkdtemp(prefix="ai-regressions-"))
        self.addCleanup(shutil.rmtree, temp, True)
        (temp / "tasks").mkdir()
        task = temp / "tasks" / "0001-x.md"
        task.write_text("---\nid: 0001\n---\nbody\n", encoding="utf-8")
        (temp / "BOARD.md").write_text("# board\n", encoding="utf-8")
        git = lambda *args: subprocess.run(
            ["git", *args], cwd=temp, check=True, capture_output=True, text=True, timeout=10
        )
        git("init", "-q")
        git("config", "user.name", "Regression Test")
        git("config", "user.email", "regression@example.test")
        git("add", "-A")
        git("commit", "-qm", "baseline")
        # the real flow mutates the task file before recording it in git
        task.write_text("---\nid: 0001\n---\nbody, updated\n", encoding="utf-8")
        hook = temp / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho 'blocked by test' >&2\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)

        events: list[tuple] = []
        stderr = io.StringIO()
        with mock.patch.object(repo, "PROJECT", str(temp)), \
                mock.patch.object(repo, "BOARD_PATH", str(temp / "BOARD.md")), \
                mock.patch.object(repo, "append_event", lambda name, **fields: events.append((name, fields))), \
                contextlib.redirect_stderr(stderr), \
                repo.working_in(str(temp)):
            result = repo.commit_task_metadata(str(task), "chore(task): record")

        self.assertIsNone(result)
        self.assertIn("task metadata was not committed", stderr.getvalue())
        self.assertTrue(any(name == "git_metadata_failed" for name, _ in events), events)


if __name__ == "__main__":
    unittest.main()
