"""One evidence state machine: resume, review and status must never disagree.

`ai resume` used to call a `--fast` check "valid" while `ai task review` refused
it, so the workspace promised proof it would not accept. `evidence.evaluate` is
now the only thing that decides, and every reader maps its verdict.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT))

from lib.runtime import evidence  # noqa: E402
from test_start import WorkspaceCase, run  # noqa: E402

HEAD = "a" * 40
OTHER = "b" * 40
GOOD = {
    "ok": True, "result": "passed", "head": HEAD, "ran_commands": True, "fast": False, "checks": [],
}


class EvidenceStateUnitTest(unittest.TestCase):
    """The state machine on its own: no CLI, no git, one evidence file."""

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="ai-evidence-state-"))
        self.addCleanup(shutil.rmtree, self.directory, True)
        patcher = mock.patch.object(evidence, "EVIDENCE_DIR", str(self.directory))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = self.directory / "0001.jsonl"

    def write(self, *records: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as handle:
            for record in records:
                row = {"task": "0001", "agent": "alice", "at": "2026-01-01T00:00:00Z"}
                row.update(record)
                handle.write(json.dumps(row) + "\n")

    def assert_verdict(self, expected: str, records, head=HEAD, since=None) -> dict:
        """Replace the evidence file and prove all three readers agree."""
        self.path.write_text("", encoding="utf-8")
        self.write(*records)
        verdict = evidence.evaluate("0001", head, since)
        self.assertEqual(verdict["state"], expected, verdict)
        self.assertIn(verdict["state"], evidence.STATES)

        status = evidence.task_status("0001", head, since)
        self.assertEqual(status["state"], expected, status)

        ok, text = evidence.task_green("0001", head, since)
        self.assertEqual(ok, expected == "green", text)
        if expected == "green":
            self.assertIn("check passed", text)
        else:
            self.assertEqual(text, verdict["reason"])
            self.assertTrue(text.strip())
        return verdict

    def test_none_is_reported_when_nothing_was_recorded(self) -> None:
        verdict = self.assert_verdict("none", [])
        self.assertEqual(verdict["record"], None)
        self.assertIn("no verification evidence is recorded for task 0001", verdict["reason"])

    def test_green_needs_full_evidence_on_this_head(self) -> None:
        self.assert_verdict("green", [GOOD])

    def test_partial_is_never_green(self) -> None:
        verdict = self.assert_verdict("partial", [{**GOOD, "fast": True, "ran_commands": False}])
        self.assertIn("--fast", verdict["reason"])
        self.assert_verdict("partial", [{**GOOD, "ran_commands": False}])

    def test_failed_check_is_failed(self) -> None:
        self.assert_verdict("failed", [{**GOOD, "ok": False, "result": "failed"}])

    def test_evidence_from_another_head_is_stale(self) -> None:
        verdict = self.assert_verdict("stale", [GOOD], head=OTHER)
        self.assertIn(HEAD[:8], verdict["reason"])
        self.assertIn(OTHER[:8], verdict["reason"])

    def test_proof_older_than_the_claim_is_stale(self) -> None:
        verdict = self.assert_verdict("stale", [GOOD], since="2027-01-01T00:00:00Z")
        self.assertIn("older than the claim", verdict["reason"])

    def test_invalidated_evidence_must_be_re_earned(self) -> None:
        verdict = self.assert_verdict(
            "invalidated", [GOOD, {"invalidated": True, "reason": "changes requested"}]
        )
        self.assertIn("changes requested", verdict["reason"])
        self.assertIn("invalidated", verdict["summary"])

    def test_the_newest_record_wins(self) -> None:
        self.assert_verdict("green", [{**GOOD, "ok": False}, GOOD])
        self.assert_verdict("failed", [GOOD, {**GOOD, "ok": False}])


class ResumeEvidenceTest(WorkspaceCase):
    """`ai resume` must not promise proof that review will refuse."""

    def configure_check(self, workspace: Path) -> None:
        path = workspace / "config" / "workspace.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["mode"] = "strict"
        config["checks"] = [{"name": "unit", "command": "python -c \"print('ok')\""}]
        path.write_text(json.dumps(config), encoding="utf-8")

    def prepare(self) -> Path:
        workspace = self.make_workspace(git_repo=False)
        self.configure_check(workspace)
        run(workspace, "task", "new", "Partial proof")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        run(workspace, "checkpoint", "0001", "--agent", "alice", "--next", "go")
        checked = run(
            workspace, "check", "--task", "0001", "--agent", "alice", "--no-commands"
        )
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        return workspace

    def test_resume_calls_a_partial_check_insufficient_for_review(self) -> None:
        workspace = self.prepare()

        resume = run(workspace, "resume", "0001").stdout

        self.assertIn("verification: PARTIAL", resume)
        self.assertIn("not enough for review", resume)
        self.assertNotIn("still valid", resume)

    def test_review_does_not_trust_the_partial_record(self) -> None:
        workspace = self.prepare()

        review = run(workspace, "task", "review", "0001", "--agent", "alice")

        # It re-runs the project checks instead of accepting the partial record.
        self.assertIn("Running the project checks", review.stderr)
        self.assertEqual(review.returncode, 0, review.stderr)

    def test_resume_still_says_valid_after_a_full_check(self) -> None:
        workspace = self.make_workspace(git_repo=False)
        self.configure_check(workspace)
        run(workspace, "task", "new", "Full proof")
        run(workspace, "task", "claim", "0001", "--agent", "alice")
        run(workspace, "checkpoint", "0001", "--agent", "alice", "--next", "go")
        run(workspace, "check", "--task", "0001", "--agent", "alice")

        self.assertIn("verification: still valid", run(workspace, "resume", "0001").stdout)

    def test_history_reports_the_shared_verdict(self) -> None:
        workspace = self.prepare()

        history = run(workspace, "history", "0001").stdout

        self.assertIn("latest partial", history)


if __name__ == "__main__":
    unittest.main()
