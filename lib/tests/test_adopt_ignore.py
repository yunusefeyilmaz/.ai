"""`ai adopt` must keep the ledger committable in a subfolder install.

The ignore file used to hide all of `.ai/`, so a subfolder install never
committed tasks, specs or decisions - the product's "durable project memory"
claim was false there. Only ephemeral state may stay local.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _workspace import copy_project

ROOT = Path(__file__).resolve().parents[2]
COPY_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", ".mypy_cache", ".ruff_cache", "*.pyc", "*.pyo",
)


def run(host: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(host / ".ai" / "ai.py"), *args],
        cwd=str(host),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )


def ignore_lines(host: Path) -> list[str]:
    text = (host / ".gitignore").read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines()]


class AdoptLedgerTest(unittest.TestCase):
    def make_host(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="ai-adopt-ledger-"))
        self.addCleanup(shutil.rmtree, temp, True)
        host = temp / "project"
        copy_project(host / ".ai")
        config = host / ".ai" / "config" / "workspace.json"
        data = json.loads(config.read_text(encoding="utf-8"))
        data["checks"] = []
        config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        (host / ".gitignore").write_text("# existing\n.ai/\nnode_modules/\n", encoding="utf-8")
        return host

    def test_the_ledger_is_not_ignored_and_the_blanket_rule_is_migrated(self) -> None:
        host = self.make_host()

        adopted = run(host, "adopt")

        self.assertEqual(adopted.returncode, 0, adopted.stderr + adopted.stdout)
        lines = ignore_lines(host)
        self.assertNotIn(".ai", lines, "a blanket .ai/ rule still hides the ledger")
        self.assertNotIn(".ai/", lines)
        self.assertIn(".ai/runtime/", lines)
        self.assertIn(".ai/worktrees/", lines)
        self.assertIn("node_modules/", lines, "unrelated ignore rules must survive")

    def test_check_accepts_the_migrated_file_and_a_second_run_is_idempotent(self) -> None:
        host = self.make_host()
        self.assertEqual(run(host, "adopt").returncode, 0)
        first = (host / ".gitignore").read_text(encoding="utf-8")

        checked = run(host, "adopt", "--check")

        self.assertEqual(checked.returncode, 0, checked.stderr + checked.stdout)
        self.assertEqual(run(host, "adopt").returncode, 0)
        self.assertEqual((host / ".gitignore").read_text(encoding="utf-8"), first)


if __name__ == "__main__":
    unittest.main()
