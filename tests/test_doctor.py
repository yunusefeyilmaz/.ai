"""Diagnostics: every finding names a safe repair, and `--fix` stays narrow.

Each test builds a throwaway copy of the framework, breaks one thing, and runs
the real CLI, so the assertions cover the same path an operator uses.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from test_start import COPY_IGNORE, ROOT, WorkspaceCase, run


def parse_json(case: unittest.TestCase, result: subprocess.CompletedProcess) -> dict:
    case.assertTrue(result.stdout.lstrip().startswith("{"), result.stderr + result.stdout)
    return json.loads(result.stdout)


def finding_with(payload: dict, needle: str) -> dict:
    for finding in payload["check"]["findings"]:
        if needle in finding["message"]:
            return finding
    raise AssertionError(f"no finding containing {needle!r} in {payload['check']['findings']}")


def clear_ledger(workspace: Path, mode: str = "lite") -> None:
    for relative in ("tasks/active", "tasks/done", "specs/active", "specs/done"):
        folder = workspace / relative
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
    for relative in ("runtime/locks", "runtime/state", "runtime/artifacts", "runtime/logs"):
        shutil.rmtree(workspace / relative, ignore_errors=True)
    (workspace / "tasks" / "BOARD.md").write_text("# Task board\n", encoding="utf-8")
    config_path = workspace / "config" / "workspace.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["mode"] = mode
    config["checks"] = []
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


class DoctorRepairTest(WorkspaceCase):
    def test_missing_runtime_is_reported_and_repaired(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        shutil.rmtree(workspace / "runtime")

        before = run(workspace, "doctor", "--json")
        self.assertEqual(before.returncode, 1, before.stderr + before.stdout)
        payload = parse_json(self, before)
        finding = finding_with(payload, "missing required path: runtime")
        self.assertEqual(finding["level"], "error")
        self.assertIn("ai doctor --fix", finding["hint"])
        self.assertFalse(
            (workspace / "runtime").exists(),
            "plain doctor must not create runtime state",
        )

        fixed = run(workspace, "doctor", "--fix", "--json")
        payload = parse_json(self, fixed)

        self.assertEqual(fixed.returncode, 0, fixed.stderr + fixed.stdout)
        self.assertTrue(any(item.startswith("created runtime") for item in payload["fixes"]))
        self.assertEqual(payload["check"]["findings"], [])
        self.assertTrue((workspace / "runtime" / "locks").is_dir())
        self.assertTrue((workspace / "runtime" / ".gitignore").is_file())

        again = run(workspace, "doctor", "--fix", "--json")
        self.assertEqual(again.returncode, 0, again.stderr + again.stdout)
        self.assertEqual(parse_json(self, again)["fixes"], [])

    def test_missing_config_is_repaired_without_touching_tasks_or_git(self) -> None:
        workspace = self.make_workspace()
        created = run(workspace, "task", "new", "Keep me", "--no-spec")
        self.assertEqual(created.returncode, 0, created.stderr)
        task = self.task_files(workspace)[0]
        task_bytes = task.read_bytes()
        head_before = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(workspace),
            capture_output=True, text=True, check=True,
        ).stdout

        (workspace / "config" / "workspace.json").unlink()
        before = run(workspace, "doctor", "--json")
        self.assertEqual(before.returncode, 1, before.stdout)
        payload = parse_json(self, before)
        findings = [
            finding for finding in payload["check"]["findings"]
            if "config/workspace.json" in finding["message"]
        ]
        self.assertEqual(len(findings), 1, findings)
        self.assertEqual(findings[0]["hint"], "ai doctor --fix")

        fixed = run(workspace, "doctor", "--fix", "--json")
        payload = parse_json(self, fixed)

        self.assertEqual(fixed.returncode, 0, fixed.stderr + fixed.stdout)
        self.assertIn("created config/workspace.json", payload["fixes"])
        self.assertEqual(payload["check"]["findings"], [])
        self.assertEqual(task.read_bytes(), task_bytes)
        self.assertEqual(
            subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=str(workspace),
                capture_output=True, text=True, check=True,
            ).stdout,
            head_before,
        )

    def test_corrupt_config_is_never_overwritten(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        config_path = workspace / "config" / "workspace.json"
        config_path.write_text("{ not json\n", encoding="utf-8")

        result = run(workspace, "doctor", "--fix", "--json")
        payload = parse_json(self, result)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(config_path.read_text(encoding="utf-8"), "{ not json\n")
        finding = finding_with(payload, "config/workspace.json is unreadable")
        self.assertTrue(finding["hint"])

    def test_orphan_lock_is_reported_but_never_removed(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        lock = workspace / "runtime" / "locks" / "task-9999.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        lock.write_text(json.dumps({
            "resource": "task-9999",
            "agent": "ghost",
            "task": "9999",
            "started_at": stamp,
            "updated_at": stamp,
            "expires_at": stamp,
            "pid": 1,
            "host": "test",
        }), encoding="utf-8")

        result = run(workspace, "doctor", "--fix", "--json")
        payload = parse_json(self, result)

        self.assertEqual(result.returncode, 1)
        self.assertTrue(lock.is_file(), "safe repair must never delete a lock")
        finding = finding_with(payload, "orphan task lock")
        self.assertIn("ai recover --apply", finding["hint"])
        self.assertFalse(any("task-9999" in item for item in payload["fixes"]))

    def test_human_output_prints_the_hint(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        (workspace / "config" / "workspace.json").unlink()

        result = run(workspace, "doctor")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("missing", result.stdout)
        self.assertIn("fix: ai doctor --fix", result.stdout)


class SubfolderDoctorTest(unittest.TestCase):
    def make_subfolder(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="ai-subfolder-doctor-"))
        self.addCleanup(shutil.rmtree, temp, True)
        project = temp / "project"
        workspace = project / ".ai"
        shutil.copytree(ROOT, workspace, ignore=COPY_IGNORE)
        clear_ledger(workspace)
        (project / "package.json").write_text("{}\n", encoding="utf-8")
        return project

    def test_missing_adapters_are_reported_and_wired(self) -> None:
        project = self.make_subfolder()
        workspace = project / ".ai"

        before = run(workspace, "doctor", "--json")
        payload = parse_json(self, before)

        self.assertEqual(before.returncode, 0, before.stderr + before.stdout)
        finding = finding_with(payload, "missing adapter pointer")
        self.assertIn("ai doctor --fix", finding["hint"])
        self.assertFalse((project / "AGENTS.md").exists())

        fixed = run(workspace, "doctor", "--fix", "--json")
        payload = parse_json(self, fixed)

        self.assertEqual(fixed.returncode, 0, fixed.stderr + fixed.stdout)
        self.assertEqual(payload["check"]["findings"], [])
        self.assertTrue((project / ".gitignore").is_file())
        self.assertIn("ai-workspace:start", (project / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertIn(".ai/", (project / ".gitignore").read_text(encoding="utf-8"))
        self.assertTrue(any(item.startswith("wired AGENTS.md") for item in payload["fixes"]))

    def test_missing_framework_file_hints_at_the_workspace_copy(self) -> None:
        project = self.make_subfolder()
        workspace = project / ".ai"
        (workspace / "docs" / "architecture.md").unlink()

        result = run(workspace, "doctor", "--json")
        payload = parse_json(self, result)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        finding = finding_with(payload, "missing required path: docs/architecture.md")
        self.assertIn("workspace", finding["hint"])
        self.assertNotIn("git checkout", finding["hint"])


if __name__ == "__main__":
    unittest.main()
