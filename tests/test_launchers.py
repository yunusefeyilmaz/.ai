"""Launchers must propagate the CLI exit code; CI depends on it."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows launcher")
class WindowsLauncherTest(unittest.TestCase):
    def call(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["cmd", "/c", str(ROOT / "scripts" / "ai.cmd"), *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

    def test_failure_exit_code_survives_the_launcher(self) -> None:
        result = self.call("task", "show", "999999")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_success_exit_code_survives_the_launcher(self) -> None:
        result = self.call("version")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ai workspace", result.stdout)


if __name__ == "__main__":
    unittest.main()
