"""The read-only board view: dependency order, lease reasons and refusals."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo")


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


class BoardCase(unittest.TestCase):
    def make_workspace(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="ai-board-"))
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
        return workspace

    def check_ok(self, workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
        result = run(workspace, *args)
        self.assertEqual(result.returncode, 0, f"{' '.join(args)}: {result.stderr}{result.stdout}")
        return result

    def write_task(
        self,
        workspace: Path,
        task_id: str,
        title: str = "Board probe",
        folder: str = "active",
        **front_matter,
    ) -> Path:
        fields = {
            "status": "todo",
            "owner": None,
            "priority": "low",
            "spec": None,
            "created": "2026-10-29T00:00:00Z",
            "updated": "2026-10-29T00:00:00Z",
            "lock": None,
            "depends_on": None,
        }
        fields.update(front_matter)
        lines = [
            "---",
            f"id: {task_id}",
            f'title: "{title}"',
            f"status: {fields['status']}",
            f"owner: {fields['owner'] or 'null'}",
            f"priority: {fields['priority']}",
            f"spec: {fields['spec'] or 'null'}",
            f"created: {fields['created']}",
            f"updated: {fields['updated']}",
            f"lock: {fields['lock'] or 'null'}",
            f"depends_on: {fields['depends_on'] or 'null'}",
            "---",
            "",
            f"# {task_id} - {title}",
            "",
            "## Log",
            "",
        ]
        path = workspace / "tasks" / folder / f"{task_id}-{title.lower().replace(' ', '-')}.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def write_checkpoint(self, workspace: Path, task_id: str, minutes_ago: int = 5) -> None:
        folder = workspace / "runtime" / "state" / "checkpoints"
        folder.mkdir(parents=True, exist_ok=True)
        created = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        (folder / f"{task_id}.md").write_text(
            f"---\ntask: {task_id}\nagent: alice\ncreated: {created}\n---\n",
            encoding="utf-8",
        )


class BoardSnapshotTest(BoardCase):
    def test_empty_board(self) -> None:
        workspace = self.make_workspace()
        result = self.check_ok(workspace, "status", "--board")
        self.assertEqual(
            result.stdout,
            "Task board\n"
            "mode: lite | active: 0 | leases: 0 | checkpoints: 0\n"
            "\n"
            "Tasks\n"
            "  (no active tasks)\n"
            "\n"
            "Leases\n"
            "  (no leases)\n"
            "\n"
            "Refusals\n"
            "  (none)\n",
        )

    def test_single_task_shows_owner_status_and_checkpoint_age(self) -> None:
        workspace = self.make_workspace()
        self.write_task(workspace, "0001", status="in_progress", owner="alice", priority="medium")
        self.write_checkpoint(workspace, "0001", minutes_ago=5)

        result = self.check_ok(workspace, "status", "--board")
        self.assertEqual(
            result.stdout,
            "Task board\n"
            "mode: lite | active: 1 | leases: 0 | checkpoints: 1\n"
            "\n"
            "Tasks\n"
            "  ID     STATUS       OWNER        PRIORITY  CHECKPOINT   WAITING ON   TITLE\n"
            "  0001   in_progress  alice        medium    5m ago       -            Board probe\n"
            "\n"
            "Leases\n"
            "  (no leases)\n"
            "\n"
            "Refusals\n"
            "  (none)\n",
        )

    def test_blocked_work_lists_dependencies_and_blocked_state(self) -> None:
        workspace = self.make_workspace()
        self.write_task(workspace, "0001", title="Done work", folder="done", status="done")
        self.write_task(workspace, "0002", title="Ready work", depends_on="0001")
        self.write_task(workspace, "0003", title="Waiting work", depends_on="0002")
        self.write_task(
            workspace, "0004", title="Blocked work", status="blocked", depends_on="0002"
        )

        result = self.check_ok(workspace, "status", "--board")
        self.assertEqual(
            result.stdout,
            "Task board\n"
            "mode: lite | active: 3 | leases: 0 | checkpoints: 0\n"
            "\n"
            "Tasks\n"
            "  ID     STATUS       OWNER        PRIORITY  CHECKPOINT   WAITING ON   TITLE\n"
            "  0002   todo         -            low       none         -            Ready work\n"
            "  0003   todo         -            low       none         0002         Waiting work\n"
            "  0004   blocked      -            low       none         blocked 0002 Blocked work\n"
            "\n"
            "Leases\n"
            "  (no leases)\n"
            "\n"
            "Refusals\n"
            "  (none)\n",
        )


    def test_dependency_order_wins_over_priority(self) -> None:
        """A dependency appears before the higher-priority task that needs it."""
        workspace = self.make_workspace()
        self.write_task(workspace, "0001", title="Foundation", priority="low")
        self.write_task(workspace, "0002", title="Dependent", priority="high", depends_on="0001")

        result = self.check_ok(workspace, "status", "--board")
        block = result.stdout.split("Tasks\n", 1)[1].split("\nLeases", 1)[0]
        rows = [line for line in block.splitlines() if line.strip()][1:]
        self.assertEqual([row.split()[0] for row in rows], ["0001", "0002"])


class BoardLeaseTest(BoardCase):
    def test_leases_show_ttl_and_remaining_time(self) -> None:
        workspace = self.make_workspace()
        self.write_task(workspace, "0001", status="in_progress", owner="alice")
        self.check_ok(
            workspace, "lock", "acquire", "src/billing", "--agent", "alice", "--task", "0001"
        )

        result = self.check_ok(workspace, "status", "--board")
        lease_rows = [line for line in result.stdout.splitlines() if "src/billing" in line]
        self.assertEqual(len(lease_rows), 1, result.stdout)
        self.assertRegex(
            lease_rows[0],
            r"^  src/billing\s+alice\s+0001\s+1800s\s+\d+s\s+held$",
        )

    def test_refusal_names_the_conflicting_resource(self) -> None:
        workspace = self.make_workspace()
        self.check_ok(workspace, "lock", "acquire", "src/billing", "--agent", "alice", "--task", "0001")
        refused = run(
            workspace, "lock", "acquire", "src/billing/writer.py", "--agent", "bob", "--task", "0002"
        )
        self.assertEqual(refused.returncode, 1, refused.stderr + refused.stdout)

        result = self.check_ok(workspace, "status", "--board")
        refusals = result.stdout.split("Refusals\n", 1)[1]
        self.assertRegex(
            refusals,
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z  bob -> src/billing/writer\.py "
            r"\(conflict: src/billing held by alice\)",
        )

    def test_lock_status_json_details_refusals(self) -> None:
        workspace = self.make_workspace()
        self.check_ok(workspace, "lock", "acquire", "src/billing", "--agent", "alice", "--task", "0001")
        refused = run(
            workspace, "lock", "acquire", "src/billing/writer.py", "--agent", "bob", "--task", "0002"
        )
        self.assertEqual(refused.returncode, 1)

        payload = json.loads(self.check_ok(workspace, "lock", "status", "--json").stdout)
        lease = next(item for item in payload if item.get("resource") == "src/billing")
        self.assertEqual(lease["state"], "held")
        self.assertIsInstance(lease["remaining_seconds"], int)
        self.assertEqual(len(lease["refusals"]), 1)
        refusal = lease["refusals"][0]
        self.assertEqual(refusal["agent"], "bob")
        self.assertEqual(refusal["resource"], "src/billing/writer.py")
        self.assertEqual(refusal["holder"], "alice")
        self.assertEqual(refusal["reason"], "conflict: src/billing held by alice")

    def test_refusal_without_recorded_conflict_degrades(self) -> None:
        workspace = self.make_workspace()
        ledger = workspace / "runtime" / "state" / "events.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(
            json.dumps(
                {
                    "timestamp": "2026-10-29T00:00:00Z",
                    "event": "lock_refused",
                    "resource": "src/legacy",
                    "agent": "bob",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        result = self.check_ok(workspace, "status", "--board")
        self.assertIn(
            "2026-10-29T00:00:00Z  bob -> src/legacy (conflict unknown)", result.stdout
        )


class BoardContractTest(BoardCase):
    def test_board_is_plain_text(self) -> None:
        workspace = self.make_workspace()
        self.write_task(workspace, "0001", status="in_progress", owner="alice")
        self.check_ok(workspace, "lock", "acquire", "src/a", "--agent", "alice", "--task", "0001")
        result = self.check_ok(workspace, "status", "--board")
        self.assertNotIn("\x1b[", result.stdout)
        self.assertNotIn("─", result.stdout)
        self.assertNotIn("│", result.stdout)

    def test_board_creates_no_state(self) -> None:
        workspace = self.make_workspace()
        self.write_task(workspace, "0001")
        before = sorted(str(path.relative_to(workspace)) for path in workspace.rglob("*") if path.is_file())
        self.check_ok(workspace, "status", "--board")
        after = sorted(str(path.relative_to(workspace)) for path in workspace.rglob("*") if path.is_file())
        self.assertEqual(before, after)

    def test_plain_status_output_is_unchanged(self) -> None:
        workspace = self.make_workspace()
        self.write_task(workspace, "0001", status="in_progress", owner="alice")
        before = self.check_ok(workspace, "status")
        self.assertIn("Workspace  :", before.stdout)
        self.assertIn("Mode       : lite", before.stdout)
        self.assertIn("Active     : 1 task(s)", before.stdout)
        self.assertNotIn("Task board", before.stdout)

        after = self.check_ok(workspace, "status", "--json")
        payload = json.loads(after.stdout)
        self.assertEqual(
            sorted(payload),
            ["active", "artifacts", "checkpoints", "handoffs", "locks", "mode", "project", "workspace"],
        )
