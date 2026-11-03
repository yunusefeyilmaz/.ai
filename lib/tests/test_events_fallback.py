"""Regression: the audit-event fallback must never raise or lose the record.

The fallback used to call ``_write_event(fallback, fallback=True)`` while the
function accepts one argument, so the "audit trail is never empty" path raised
``TypeError`` exactly when it was needed.
"""

from __future__ import annotations

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib.runtime import events


class EventsFallbackTest(unittest.TestCase):
    def test_fallback_is_written_after_two_failures(self) -> None:
        calls: list[dict] = []

        def fake_write(record: dict) -> None:
            calls.append(record)
            if len(calls) <= 2:
                raise OSError("disk full")

        stderr = io.StringIO()
        with mock.patch.object(events, "_write_event", fake_write), \
                contextlib.redirect_stderr(stderr):
            events.append_event("probe", task="0001")

        self.assertEqual(len(calls), 3, "two attempts plus one fallback record")
        self.assertTrue(calls[2].get("_fallback"))
        self.assertEqual(calls[2].get("task"), "0001")
        self.assertIn("WARN", stderr.getvalue())
        self.assertIn("disk full", stderr.getvalue())

    def test_a_failing_fallback_still_does_not_escape(self) -> None:
        def always_fail(record: dict) -> None:
            raise OSError("ledger is gone")

        stderr = io.StringIO()
        with mock.patch.object(events, "_write_event", always_fail), \
                contextlib.redirect_stderr(stderr):
            events.append_event("probe")  # must not raise

        self.assertIn("WARN", stderr.getvalue())
        self.assertIn("fallback also failed", stderr.getvalue())

    def test_an_unwritable_ledger_path_does_not_raise(self) -> None:
        temp = Path(tempfile.mkdtemp(prefix="ai-events-"))
        self.addCleanup(shutil.rmtree, temp, True)
        ledger = temp / "events.jsonl"
        ledger.mkdir()  # a directory where a file is expected: os.open fails

        stderr = io.StringIO()
        with mock.patch.object(events, "EVENTS_FILE", str(ledger)), \
                mock.patch.object(events, "STATE_DIR", str(temp)), \
                mock.patch.object(events, "ensure_dirs", lambda: None), \
                mock.patch.object(events, "registry_mutex", lambda: contextlib.nullcontext()), \
                contextlib.redirect_stderr(stderr):
            events.append_event("probe")

        self.assertIn("WARN", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
