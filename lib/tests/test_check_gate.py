"""No silent green: an empty check gate is refused, not recorded as proof.

`ai check` used to exit 0 when `config/workspace.json` had no `checks`; that
empty result could then be cited as evidence. These tests pin the refusal, the
explicit `--allow-empty` opt-out, and the strict review gate behind them.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from _workspace import make_workspace as build_workspace


def checks_disabled(config: dict) -> None:
    """What `ai setup --set checks=no` writes: the project declines verification."""
    config.setdefault("workflow", {})["requireCheck"] = False


def run(workspace: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(workspace / "ai.py"), *args],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )


class CheckGateTest(unittest.TestCase):
    def make_workspace(self, mode: str = "lite", configure=None) -> Path:
        return build_workspace(self, "ai-check-gate-", mode=mode, configure=configure)

    def test_no_configured_checks_is_refused(self) -> None:
        workspace = self.make_workspace()

        result = run(workspace, "check")
        output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 1, output)
        self.assertIn("no project checks are configured", output)
        self.assertIn("config/workspace.json", output)
        self.assertIn("--allow-empty", output)

    def test_allow_empty_is_an_explicit_printed_opt_out(self) -> None:
        workspace = self.make_workspace()

        result = run(workspace, "check", "--allow-empty")
        output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("ALLOW-EMPTY", output)
        self.assertIn("no project checks are configured", output)
        self.assertIn("--allow-empty", output)

    def test_allow_empty_is_machine_readable_in_json_mode(self) -> None:
        workspace = self.make_workspace()

        result = run(workspace, "check", "--allow-empty", "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["allow_empty"])
        self.assertEqual(payload["results"], [])
        self.assertIn("ALLOW-EMPTY", result.stderr)
        self.assertIn("no project checks are configured", result.stderr)

    def test_checks_disabled_in_config_is_a_printed_opt_out(self) -> None:
        workspace = self.make_workspace(configure=checks_disabled)

        result = run(workspace, "check")
        output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("ALLOW-EMPTY", output)
        self.assertIn("requireCheck", output)

    def test_empty_check_records_no_green_evidence(self) -> None:
        workspace = self.make_workspace()
        run(workspace, "task", "new", "No proof", "--no-spec")
        run(workspace, "task", "claim", "0001", "--agent", "alice")

        checked = run(workspace, "check", "--task", "0001", "--agent", "alice")

        self.assertEqual(checked.returncode, 1, checked.stdout + checked.stderr)
        self.assertIn("Evidence recorded", checked.stderr)
        resume = run(workspace, "resume", "0001").stdout
        self.assertNotIn("still valid", resume)

    def test_strict_review_cannot_pass_on_empty_verification(self) -> None:
        workspace = self.make_workspace(mode="strict")
        run(workspace, "task", "new", "Strict", "--no-spec")
        run(workspace, "task", "claim", "0001", "--agent", "alice")

        reviewed = run(workspace, "task", "review", "0001", "--agent", "alice")

        self.assertEqual(reviewed.returncode, 1, reviewed.stdout + reviewed.stderr)
        self.assertIn("no project checks", reviewed.stderr)


if __name__ == "__main__":
    unittest.main()
