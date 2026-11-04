"""`ai now --json` tells a harness whether to act or to ask the user.

The schema is versioned: a consumer reads `needs_human`, `question`, `next_args`
and `blocker` instead of parsing the prose in `why`. `next_args` is the exact
argv of the printed NEXT line, so it can be executed unchanged.
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

from _workspace import GitSpec
from _workspace import make_workspace as build_workspace

ROOT = Path(__file__).resolve().parents[2]
COPY_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", ".mypy_cache", ".ruff_cache", "*.pyc", "*.pyo",
)


def run(workspace: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
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


def _configure_now_json(config: dict) -> None:
    config["preferences"] = {"confirmed": False, "answered": []}
    workflow = config.setdefault("workflow", {})
    workflow["chiefOnlyTasks"] = False
    workflow["requireSpec"] = False
    workflow["requireCheck"] = False
    workflow["autoContinue"] = False


class NowJsonCase(unittest.TestCase):
    def make_workspace(self) -> Path:
        spec = GitSpec("master", "Now JSON Test", "now@example.test", ("develop",))
        return build_workspace(self, "ai-now-json-", git=spec, configure=_configure_now_json)

    def payload(self, workspace: Path, *args: str) -> dict:
        result = run(workspace, "now", "--json", *args)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def create_task(self, workspace: Path) -> None:
        created = run(workspace, "task", "new", "Now json scenario", "--no-spec")
        self.assertEqual(created.returncode, 0, created.stderr + created.stdout)

    def test_schema_two_publishes_the_four_contract_keys(self) -> None:
        payload = self.payload(self.make_workspace(), "--agent", "alice")
        self.assertEqual(payload["schema"], 2)
        for key in ("needs_human", "question", "next_args", "blocker"):
            self.assertIn(key, payload)
        self.assertIsInstance(payload["needs_human"], bool)
        self.assertIsInstance(payload["next_args"], list)
        self.assertIsInstance(payload["recommended"], dict)

    def test_asking_the_setup_questions_needs_the_human(self) -> None:
        payload = self.payload(self.make_workspace(), "--agent", "alice")
        self.assertTrue(payload["needs_human"])
        self.assertIn("process", payload["question"].lower())
        self.assertEqual(payload["next_args"], ["setup"])
        self.assertTrue(payload["blocker"])

    def test_a_ready_task_is_actionable_with_the_callers_agent_name(self) -> None:
        workspace = self.make_workspace()
        self.create_task(workspace)
        config_path = workspace / "config" / "workspace.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["preferences"] = {
            "confirmed": True, "answered": ["review", "checks", "git", "tests"],
        }
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        payload = self.payload(workspace, "--agent", "alice")
        self.assertFalse(payload["needs_human"])
        self.assertIsNone(payload["question"])
        self.assertIsNone(payload["blocker"])
        self.assertEqual(payload["next_args"], ["task", "next", "--agent", "alice"])
        self.assertNotIn("<n>", json.dumps(payload["next_args"]))

    def test_next_args_matches_the_printed_next_line(self) -> None:
        workspace = self.make_workspace()
        self.create_task(workspace)
        claimed = run(workspace, "task", "claim", "0001", "--agent", "alice")
        self.assertEqual(claimed.returncode, 0, claimed.stdout + claimed.stderr)

        payload = self.payload(workspace, "--agent", "alice")
        self.assertFalse(payload["needs_human"])
        next_line = next(
            line for line in run(workspace, "now", "--agent", "alice").stdout.splitlines()
            if line.startswith("NEXT")
        )
        printed = next_line[len("NEXT"):].strip().split()
        self.assertEqual(printed[0], "ai")
        self.assertEqual(printed[1:], payload["next_args"])
        self.assertNotIn("<n>", " ".join(payload["next_args"]))

    def test_delivered_work_waits_for_the_human(self) -> None:
        workspace = self.make_workspace()
        self.create_task(workspace)
        self.assertEqual(run(workspace, "task", "claim", "0001", "--agent", "alice").returncode, 0)
        reviewed = run(workspace, "task", "review", "0001", "--agent", "alice")
        self.assertEqual(reviewed.returncode, 0, reviewed.stdout + reviewed.stderr)

        payload = self.payload(workspace, "--agent", "alice")
        self.assertTrue(payload["needs_human"])
        self.assertEqual(payload["next_args"], [])
        self.assertIn("0001", payload["question"])

    def test_the_text_output_is_unchanged_in_shape(self) -> None:
        workspace = self.make_workspace()
        self.create_task(workspace)
        result = run(workspace, "now", "--agent", "alice")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        lines = result.stdout.strip().splitlines()
        self.assertTrue(lines[0].startswith("ai "), lines[0])
        labels = [line.split()[0] for line in lines if line.split()]
        self.assertIn("NEXT", labels)
        self.assertIn("WHY", labels)
        self.assertNotIn("schema", result.stdout)
        self.assertTrue(lines[-1].startswith("More:"))


if __name__ == "__main__":
    unittest.main()
