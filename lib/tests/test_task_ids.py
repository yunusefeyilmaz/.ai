"""Task ids scale past 9999: one constant drives every check and hint."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib.core import fsio
from lib.runtime import health
from lib.specs import spec as spec_lib
from lib.tasks import store


class TaskIdLimitTest(unittest.TestCase):
    def test_five_and_nine_digit_ids_are_canonical(self) -> None:
        self.assertEqual(fsio.normalize_id("10000"), "10000")
        self.assertEqual(fsio.normalize_id("T-10000"), "10000")
        self.assertEqual(fsio.normalize_id("task-123456789"), "123456789")
        self.assertEqual(fsio.normalize_id("7"), "0007")

    def test_ten_digits_name_the_single_limit(self) -> None:
        self.assertEqual(fsio.MAX_TASK_ID_DIGITS, 9)
        with self.assertRaises(ValueError) as caught:
            fsio.normalize_id("1234567890")
        self.assertIn(f"{fsio.MAX_TASK_ID_DIGITS} digits", str(caught.exception))

    def test_leading_zeros_do_not_bypass_the_limit(self) -> None:
        with self.assertRaises(ValueError):
            fsio.normalize_id("0" * 20 + "1234567890")

    def test_doctor_hint_uses_the_same_constant(self) -> None:
        self.assertIn(f"{fsio.MAX_TASK_ID_DIGITS} digits", health.TASK_ID_HINT)

    def test_task_lookup_accepts_a_five_digit_id(self) -> None:
        temp = Path(tempfile.mkdtemp(prefix="ai-ids-"))
        self.addCleanup(shutil.rmtree, temp, True)
        active = temp / "active"
        (temp / "done").mkdir()
        active.mkdir()
        task = active / "10000-big-ledger.md"
        task.write_text("---\nid: 10000\ntitle: Big ledger\nstatus: todo\n---\nbody\n", encoding="utf-8")
        with mock.patch.object(store, "TASKS_DIR", str(temp)):
            self.assertEqual(store.find_task("10000"), str(task))

    def test_spec_lookup_by_five_digit_id(self) -> None:
        temp = Path(tempfile.mkdtemp(prefix="ai-ids-"))
        self.addCleanup(shutil.rmtree, temp, True)
        specs = temp / "specs"
        (specs / "active").mkdir(parents=True)
        (specs / "done").mkdir()
        spec = specs / "active" / "10000-big-ledger.md"
        spec.write_text("# 10000\n", encoding="utf-8")
        with mock.patch.object(spec_lib, "PROJECT", str(temp)), \
                mock.patch.object(spec_lib, "WORKSPACE", str(temp)), \
                mock.patch.object(spec_lib, "SPECS_DIR", str(specs)):
            resolved = spec_lib.resolve_spec_path({"spec": "10000"})
        self.assertEqual(resolved, str(spec))


if __name__ == "__main__":
    unittest.main()
