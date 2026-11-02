"""Platform and crash-safety regressions that do not need a real Windows box.

The suite runs on every OS. These tests inject the failure modes a platform
contributes — a sharing violation, a missing git binary, a write killed
mid-flight, a CRLF task file — at the `fsio` / `repo` boundary instead of
skipping on non-Windows runners.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib.core import fsio  # noqa: E402
from lib.git import repo  # noqa: E402
from lib.tasks import store  # noqa: E402


class AtomicWriteFaultTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="ai-platform-"))
        self.addCleanup(shutil.rmtree, self.temp, True)

    def test_failed_fsync_keeps_the_previous_content(self) -> None:
        target = self.temp / "state.json"
        target.write_text('{"ok": true}\n', encoding="utf-8")

        with mock.patch.object(fsio.os, "fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                fsio.write_json_atomic(str(target), {"ok": False})

        self.assertEqual(target.read_text(encoding="utf-8"), '{"ok": true}\n')
        leftovers = [name for name in os.listdir(self.temp) if name.startswith(".tmp-")]
        self.assertEqual(leftovers, [], "a failed write must not leave temp debris")

    def test_windows_sharing_violation_is_retried(self) -> None:
        target = self.temp / "state.json"
        real_replace = os.replace
        calls = {"count": 0}

        def flaky_replace(source, destination):
            calls["count"] += 1
            if calls["count"] < 3:
                raise PermissionError("file is open in another program")
            return real_replace(source, destination)

        with mock.patch.object(fsio.os, "replace", side_effect=flaky_replace):
            fsio.write_json_atomic(str(target), {"retried": True})

        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"retried": True})
        self.assertEqual(calls["count"], 3, "the replace should be retried, then succeed")


class GitAvailabilityTest(unittest.TestCase):
    def test_missing_git_binary_is_reported(self) -> None:
        with mock.patch.object(repo.subprocess, "run", side_effect=FileNotFoundError("git")):
            code, _, error = repo.run_git(["status"])
        self.assertEqual(code, 127)
        self.assertIn("git is not available", error)

    def test_git_timeout_is_reported(self) -> None:
        timeout = repo.subprocess.TimeoutExpired("git", 1)
        with mock.patch.object(repo.subprocess, "run", side_effect=timeout):
            code, _, error = repo.run_git(["status"])
        self.assertEqual(code, 124)
        self.assertIn("timed out", error)


class TaskFileEncodingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="ai-platform-"))
        self.addCleanup(shutil.rmtree, self.temp, True)

    def test_crlf_task_file_parses_and_round_trips_to_lf(self) -> None:
        path = self.temp / "0001-windows.md"
        path.write_bytes(
            b"---\r\nid: 0001\r\ntitle: Windows\r\nstatus: todo\r\n---\r\nbody line\r\n"
        )

        meta, body = store.parse_task(str(path))
        self.assertEqual(meta["id"], "0001")
        self.assertEqual(meta["title"], "Windows")
        self.assertEqual(store.frontmatter_problems(str(path)), [])
        self.assertEqual(body.strip(), "body line")

        store.write_task(str(path), meta, body)
        self.assertNotIn(b"\r\n", path.read_bytes(), "the CLI always writes LF")


if __name__ == "__main__":
    unittest.main()
