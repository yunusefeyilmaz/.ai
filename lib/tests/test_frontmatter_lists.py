"""Flow-style front matter lists must survive parsing instead of becoming one string."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib.tasks import store  # noqa: E402


class FrontmatterListTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="ai-frontmatter-"))
        self.addCleanup(shutil.rmtree, self.temp, True)

    def parse(self, frontmatter: str):
        path = self.temp / "0001-probe.md"
        path.write_text(f"---\n{frontmatter}\n---\n\nbody\n", encoding="utf-8")
        return store.parse_task(str(path))

    def test_flow_dependencies_become_real_dependencies(self) -> None:
        meta, _ = self.parse("id: 0001\ntitle: One\nstatus: todo\ndepends_on: [0001, 0002]")
        self.assertEqual(meta["depends_on"], "0001, 0002")
        self.assertEqual(store.board_dependencies(meta), ["0001", "0002"])

    def test_quoted_items_spacing_and_single_quotes(self) -> None:
        meta, _ = self.parse(
            "id: 0001\ntitle: One\nstatus: todo\n"
            "locks: [ \"lib/a.py\",  'lib/b.py' ,lib/c.py ]"
        )
        self.assertEqual(meta["locks"], "lib/a.py, lib/b.py, lib/c.py")

    def test_empty_flow_list_means_no_value(self) -> None:
        meta, _ = self.parse("id: 0001\ntitle: One\nstatus: todo\ndepends_on: []")
        self.assertIsNone(meta["depends_on"])
        self.assertEqual(store.board_dependencies(meta), [])

    def test_unterminated_flow_list_is_reported_not_swallowed(self) -> None:
        path = self.temp / "0001-broken.md"
        path.write_text(
            "---\nid: 0001\ntitle: One\nstatus: todo\ndepends_on: [0001, 0002\n---\n",
            encoding="utf-8",
        )
        problems = store.frontmatter_problems(str(path))
        self.assertTrue(any("unterminated flow list" in item for item in problems), problems)
        meta, _ = store.parse_task(str(path))
        self.assertIsNone(meta["depends_on"])

    def test_trailing_text_after_a_flow_list_is_reported(self) -> None:
        path = self.temp / "0001-trailing.md"
        path.write_text(
            "---\nid: 0001\ntitle: One\nstatus: todo\ndepends_on: [0001] oops\n---\n",
            encoding="utf-8",
        )
        problems = store.frontmatter_problems(str(path))
        self.assertTrue(any("unexpected text after flow list" in item for item in problems), problems)

    def test_written_lists_round_trip_as_comma_separated(self) -> None:
        path = self.temp / "0001-round.md"
        meta = {
            "id": "0001",
            "title": "One",
            "status": "todo",
            "depends_on": ["0002", "0003"],
            "locks": ["lib/a.py", "lib/b.py"],
        }
        store.write_task(str(path), meta, "body\n")
        text = path.read_text(encoding="utf-8")
        self.assertIn("depends_on: 0002, 0003", text)
        self.assertNotIn("[", text)
        parsed, _ = store.parse_task(str(path))
        self.assertEqual(store.board_dependencies(parsed), ["0002", "0003"])
        self.assertEqual(parsed["locks"], "lib/a.py, lib/b.py")

    def test_scalar_values_keep_their_behavior(self) -> None:
        meta, _ = self.parse(
            "id: 0001\ntitle: \"Two, three\"\nstatus: todo\nscope_allowed: src/[ab].py"
        )
        self.assertEqual(meta["title"], "Two, three")
        self.assertEqual(meta["scope_allowed"], "src/[ab].py")


if __name__ == "__main__":
    unittest.main()
