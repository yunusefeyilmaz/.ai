"""First-run behavior: `ai start` and the spec skeleton written by `task new`.

Each test builds a throwaway copy of the framework so it exercises the real CLI
and never touches the checkout running the suite.
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

ROOT = Path(__file__).resolve().parents[2]
COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo")


def run(workspace: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(workspace / "ai.py"), *args],
        cwd=str(workspace),
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )


def git(workspace: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(workspace),
        check=True,
        capture_output=True,
        text=True,
    )


class WorkspaceCase(unittest.TestCase):
    def make_workspace(self, git_repo: bool = True, mode: str = "lite") -> Path:
        temp = Path(tempfile.mkdtemp(prefix="ai-first-run-"))
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
        config["mode"] = mode
        config["checks"] = []
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        if git_repo:
            git(workspace, "init", "-q", "--initial-branch=main")
            git(workspace, "config", "user.name", "Test Runner")
            git(workspace, "config", "user.email", "test@example.com")
            git(workspace, "add", "-A")
            git(workspace, "commit", "-qm", "test baseline")
        return workspace

    def start(self, workspace: Path, *extra: str) -> dict:
        result = run(workspace, "start", "--json", *extra)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def task_files(self, workspace: Path) -> list[Path]:
        return sorted((workspace / "tasks" / "active").glob("*.md"))


class StartTest(WorkspaceCase):
    def test_start_creates_one_task_and_a_linked_spec(self) -> None:
        workspace = self.make_workspace()
        payload = self.start(workspace)

        self.assertEqual(payload["shape"], "root")
        self.assertEqual(payload["mode"], "lite")
        self.assertTrue(payload["git"]["ready"])
        self.assertEqual(payload["git"]["integration"], "develop")
        self.assertEqual(payload["git"]["production"], "master")

        tasks = self.task_files(workspace)
        self.assertEqual(len(tasks), 1)
        text = tasks[0].read_text(encoding="utf-8")
        self.assertIn("spec: specs/active/", text)
        spec = workspace / payload["task"]["spec"]
        self.assertTrue(spec.is_file())
        self.assertIn(f"task: {payload['task']['id']}", spec.read_text(encoding="utf-8"))
        self.assertIn("ai check --fast", "\n".join(payload["next"]))

    def test_agent_claims_the_starter_task(self) -> None:
        workspace = self.make_workspace()
        payload = self.start(workspace, "--agent", "newcomer")

        self.assertTrue(payload["claimed"])
        self.assertEqual(payload["task"]["owner"], "newcomer")
        self.assertIn("ai git start --task 0001 --agent newcomer", "\n".join(payload["next"]))

    def test_second_start_adds_nothing(self) -> None:
        workspace = self.make_workspace()
        self.start(workspace)
        payload = self.start(workspace)

        self.assertFalse(payload["created"])
        self.assertEqual(len(self.task_files(workspace)), 1)

    def test_start_does_not_prompt_without_a_commit(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        result = run(workspace, "start", "--json", stdin="")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["git"]["ready"])
        self.assertIn("ai git setup", payload["next"])
        self.assertEqual(len(self.task_files(workspace)), 1)

    def test_no_demo_leaves_the_ledger_empty(self) -> None:
        workspace = self.make_workspace()
        payload = self.start(workspace, "--no-demo")

        self.assertIsNone(payload["task"])
        self.assertEqual(self.task_files(workspace), [])
        self.assertIn('ai task new "<title>"', payload["next"])


class TaskSpecTest(WorkspaceCase):
    def test_task_new_writes_and_links_a_spec(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        result = run(workspace, "task", "new", "Write the parser")

        self.assertEqual(result.returncode, 0, result.stderr)
        task = self.task_files(workspace)[0]
        text = task.read_text(encoding="utf-8")
        spec_path = workspace / "specs" / "active" / f"{task.stem.split('-')[0]}-write-the-parser.md"
        self.assertTrue(spec_path.is_file())
        self.assertIn(spec_path.relative_to(workspace).as_posix(), text)
        self.assertIn("task: 0001", spec_path.read_text(encoding="utf-8"))

    def test_no_spec_keeps_the_ledger_only(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        result = run(workspace, "task", "new", "Quick fix", "--no-spec")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("spec: null", self.task_files(workspace)[0].read_text(encoding="utf-8"))
        self.assertEqual(list((workspace / "specs" / "active").glob("*.md")), [])

    def test_explicit_spec_is_linked_and_untouched(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        custom = workspace / "specs" / "active" / "custom.md"
        custom.write_text("# Custom\n\nkeep me\n", encoding="utf-8")
        result = run(workspace, "task", "new", "Linked spec", "--spec", "specs/active/custom.md")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("spec: specs/active/custom.md", self.task_files(workspace)[0].read_text(encoding="utf-8"))
        self.assertEqual(custom.read_text(encoding="utf-8"), "# Custom\n\nkeep me\n")


class FirstRunLoopTest(WorkspaceCase):
    def test_started_task_can_open_its_branch(self) -> None:
        workspace = self.make_workspace()
        payload = self.start(workspace, "--agent", "newcomer")

        result = run(
            workspace, "git", "start", "--task", payload["task"]["id"],
            "--agent", "newcomer", "--type", "feature",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(workspace), capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertTrue(branch.startswith("feature/0001-"), branch)

    def test_product_changes_still_block_the_branch(self) -> None:
        workspace = self.make_workspace()
        payload = self.start(workspace, "--agent", "newcomer")
        (workspace / "src").mkdir(exist_ok=True)
        (workspace / "src" / "app.py").write_text("pass\n", encoding="utf-8")

        result = run(
            workspace, "git", "start", "--task", payload["task"]["id"],
            "--agent", "newcomer", "--type", "feature",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("product changes", result.stderr)

    def test_done_only_ledger_creates_a_new_task(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        created = run(workspace, "task", "new", "Seed")
        self.assertEqual(created.returncode, 0, created.stderr)
        archived = run(workspace, "task", "done", "0001", "--agent", "seed", "--force")
        self.assertEqual(archived.returncode, 0, archived.stderr)

        payload = self.start(workspace, "--agent", "newcomer")

        self.assertTrue(payload["created"])
        self.assertEqual(payload["task"]["id"], "0002")
        self.assertEqual(payload["task"]["owner"], "newcomer")

    def test_first_porcelain_entry_keeps_tasks_board_path(self) -> None:
        workspace = self.make_workspace()
        started = run(workspace, "start", "--agent", "me")
        self.assertEqual(started.returncode, 0, started.stderr + started.stdout)

        # This is a tracked, worktree-only edit. Its porcelain record begins
        # with a space; trimming command output used to turn the path into
        # `asks/BOARD.md`, making git start treat ledger state as product code.
        (workspace / "tasks" / "BOARD.md").write_text("# changed\n", encoding="utf-8")
        result = run(
            workspace, "git", "start", "--task", "0001", "--agent", "me", "--type", "feature",
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


class LiteCheckpointTest(WorkspaceCase):
    def test_lite_does_not_warn_on_a_fresh_claim(self) -> None:
        workspace = self.make_workspace(mode="lite")
        self.start(workspace, "--agent", "me")
        result = run(workspace, "check", "--strict")

        self.assertNotIn("no checkpoint", result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_strict_warns_on_a_fresh_claim(self) -> None:
        workspace = self.make_workspace(mode="strict")
        self.start(workspace, "--agent", "me")
        result = run(workspace, "check", "--strict")

        self.assertIn("no checkpoint", result.stdout)
        self.assertEqual(result.returncode, 1)

    def test_old_checkpoint_warns_in_lite(self) -> None:
        workspace = self.make_workspace(mode="lite")
        self.start(workspace, "--agent", "me")
        checkpoint = run(workspace, "checkpoint", "0001", "--agent", "me", "--next", "continue")
        self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr)

        path = workspace / "runtime" / "state" / "checkpoints" / "0001.md"
        text = path.read_text(encoding="utf-8")
        lines = []
        for line in text.splitlines():
            lines.append("created: 2020-01-01T00:00:00Z" if line.startswith("created: ") else line)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = run(workspace, "check", "--strict")
        self.assertIn("last checkpoint is", result.stdout)


if __name__ == "__main__":
    unittest.main()
