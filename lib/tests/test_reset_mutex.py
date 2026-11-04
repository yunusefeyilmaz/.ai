"""`ai reset --hard` checks locks and deletes state inside the registry mutex.

The reset used to re-check locks and then delete files outside `registry_mutex()`,
so a lock or a state write could land between the check and the deletion and a
writer could observe a half-deleted workspace. `cmd_reset` is interactive, so the
test drives it in-process in a throwaway copy of the workspace and probes the
mutex from separate processes - an advisory lock is only observable across
processes, not inside the one holding it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COPY_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", ".mypy_cache", ".ruff_cache", "*.pyc", "*.pyo",
)
CONFIRMATION = "reset .ai hard"

MUTEX_PROBE = """
import sys

sys.path.insert(0, sys.argv[1])

from lib.runtime.mutex import registry_mutex

try:
    with registry_mutex(timeout=0.25):
        print("free")
except TimeoutError:
    print("busy")
"""

GUARD_PROBE = """
import sys

sys.path.insert(0, sys.argv[1])

from lib.runtime.mutex import workspace_state_guard

try:
    with workspace_state_guard():
        print("observed")
except (TimeoutError, RuntimeError):
    print("refused")
"""

DRIVER = """
import builtins
import json
import os
import subprocess
import sys

workspace, mutex_probe, guard_probe, mode, output = sys.argv[1:6]
sys.path.insert(0, workspace)
os.chdir(workspace)

from lib.cmd import reset as reset_cmd

log = []


def probe(path):
    try:
        result = subprocess.run(
            [sys.executable, path, workspace],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except subprocess.TimeoutExpired:
        # `workspace_state_guard()` waits 10s on the mutex before giving up; the
        # test only needs to know that it never got in.
        return "refused"
    return result.stdout.strip() or "no-output"


def write_stray_lock():
    folder = os.path.join(workspace, "runtime", "locks")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "intruder.lock"), "w", encoding="utf-8") as handle:
        handle.write("{}")


real_acquire = reset_cmd.acquire_lock
real_remove = os.remove
real_release = reset_cmd.release_lock


def spy_acquire(*args, **kwargs):
    result = real_acquire(*args, **kwargs)
    if mode == "lock" and result.get("ok"):
        # A lock that lands after the pre-flight check but before the critical
        # section: only the re-check inside the mutex can still catch it.
        write_stray_lock()
    return result


def spy_remove(path):
    if not log:
        log.append(
            {
                "during_delete_mutex": probe(mutex_probe),
                "during_delete_guard": probe(guard_probe),
            }
        )
    target = str(path).replace("\\\\", "/")
    if mode == "fail" and "/tasks/active/" in target and target.endswith(".md"):
        raise OSError("disk full")
    return real_remove(path)


def spy_release(*args, **kwargs):
    log.append({"release_mutex": probe(mutex_probe)})
    return real_release(*args, **kwargs)


class FakeTTY:
    def isatty(self):
        return True

    def readline(self):
        return "%(confirmation)s\\n"


reset_cmd.acquire_lock = spy_acquire
os.remove = spy_remove
reset_cmd.release_lock = spy_release
builtins.input = lambda prompt="": "%(confirmation)s"
sys.stdin = FakeTTY()

code = reset_cmd.cmd_reset(type("Args", (), {"hard": True})())

os.remove = real_remove
reset_cmd.acquire_lock = real_acquire
reset_cmd.release_lock = real_release

active = os.path.join(workspace, "tasks", "active")
board_path = os.path.join(workspace, "tasks", "BOARD.md")
locks = os.path.join(workspace, "runtime", "locks")
with open(output, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "code": code,
            "checks": log,
            "active": sorted(os.listdir(active)) if os.path.isdir(active) else [],
            "marker": os.path.exists(os.path.join(workspace, "runtime", "artifacts", "probe-marker.txt")),
            "locks": sorted(name for name in os.listdir(locks) if name.endswith(".lock"))
            if os.path.isdir(locks)
            else [],
            "board": open(board_path, encoding="utf-8").read()
            if os.path.exists(board_path)
            else "",
        },
        handle,
    )
""" % {"confirmation": CONFIRMATION}


class ResetMutexTest(unittest.TestCase):
    def make_workspace(self) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="ai-reset-mutex-"))
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
        # The developer's `ai setup` answers must not change what the suite gates on.
        config.setdefault("workflow", {})["requireCheck"] = "strict"
        config.setdefault("preferences", {})["confirmed"] = False
        config["preferences"]["answered"] = []
        config.setdefault("workflow", {})["chiefOnlyTasks"] = False
        config["workflow"]["requireSpec"] = False
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        for title in ("Reset one", "Reset two"):
            created = subprocess.run(
                [sys.executable, str(workspace / "ai.py"), "task", "new", title, "--no-spec"],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            self.assertEqual(created.returncode, 0, created.stderr + created.stdout)
        artifacts = workspace / "runtime" / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "probe-marker.txt").write_text("reset me\n", encoding="utf-8")
        return workspace

    def drive(self, workspace: Path, mode: str) -> dict:
        temp = Path(tempfile.mkdtemp(prefix="ai-reset-driver-"))
        self.addCleanup(shutil.rmtree, temp, True)
        mutex_probe = temp / "mutex_probe.py"
        guard_probe = temp / "guard_probe.py"
        driver = temp / "driver.py"
        mutex_probe.write_text(MUTEX_PROBE, encoding="utf-8")
        guard_probe.write_text(GUARD_PROBE, encoding="utf-8")
        driver.write_text(DRIVER, encoding="utf-8")
        output = temp / "result.json"

        result = subprocess.run(
            [sys.executable, str(driver), str(workspace), str(mutex_probe), str(guard_probe), mode, str(output)],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        if not output.is_file() or not output.read_text(encoding="utf-8").strip():
            self.fail(f"the reset driver produced no result\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        return json.loads(output.read_text(encoding="utf-8"))

    def test_the_deletion_and_the_final_check_run_under_the_mutex(self) -> None:
        workspace = self.make_workspace()

        payload = self.drive(workspace, "clean")

        self.assertEqual(payload["code"], 0, payload)
        during = payload["checks"][0]
        self.assertEqual(during["during_delete_mutex"], "busy", "another process acquired the mutex mid-deletion")
        self.assertEqual(during["during_delete_guard"], "refused", "a state writer observed the half-deleted workspace")
        self.assertEqual(payload["active"], [])
        self.assertFalse(payload["marker"], "the reset did not remove the state files")

    def test_the_project_lock_is_released_only_after_the_mutex(self) -> None:
        workspace = self.make_workspace()

        payload = self.drive(workspace, "clean")

        released = [check["release_mutex"] for check in payload["checks"] if "release_mutex" in check]
        self.assertEqual(released, ["free"], "the project lock was released while the mutex was still held")
        self.assertEqual(payload["locks"], [])

    def test_a_lock_that_appears_during_confirmation_cancels_the_reset(self) -> None:
        workspace = self.make_workspace()

        payload = self.drive(workspace, "lock")

        self.assertEqual(payload["code"], 1, payload)
        self.assertEqual(len(payload["active"]), 2, "the reset deleted files after a lock appeared")
        self.assertTrue(payload["marker"], "the reset deleted state files after a lock appeared")
        self.assertEqual(payload["locks"], ["intruder.lock"], "the reset lock must be released, the stray one kept")

    def test_a_filesystem_failure_reports_the_partial_cleanup_and_refreshes_the_board(self) -> None:
        workspace = self.make_workspace()
        (workspace / "tasks" / "BOARD.md").write_text("# Task board\n\nSTALE-MARKER\n", encoding="utf-8")

        payload = self.drive(workspace, "fail")

        self.assertEqual(payload["code"], 1, payload)
        self.assertIn("Active: 2", payload["board"])
        self.assertNotIn("STALE-MARKER", payload["board"], "the board must be refreshed after a partial cleanup")
        self.assertFalse(payload["marker"], "the failure should leave the earlier deletions in place")
        self.assertEqual(payload["locks"], [])


if __name__ == "__main__":
    unittest.main()
