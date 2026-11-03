"""`ai capabilities` is derived from the parser, so the contract cannot drift.

The hand-maintained table silently missed real flags (`ai check --task`,
`--agent`, `--no-commands`), which is exactly the drift a machine-readable
contract exists to prevent. These tests build the same parser the CLI builds and
compare it with the published JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from test_start import run  # noqa: E402


def parser_contract() -> dict[str, set[str]]:
    """Every command path the CLI defines, mapped to its option strings."""
    from ai import build_parser

    def walk(action: argparse._SubParsersAction, prefix: str, out: dict[str, set[str]]) -> None:
        for name, sub in action.choices.items():
            path = f"{prefix} {name}".strip()
            flags: set[str] = set()
            for sub_action in sub._actions:
                flags.update(sub_action.option_strings)
            out[path] = flags
            for sub_action in sub._actions:
                if isinstance(sub_action, argparse._SubParsersAction):
                    walk(sub_action, path, out)

    parser = build_parser([])
    contract: dict[str, set[str]] = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            walk(action, "", contract)
    return contract


class CapabilitiesContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        result = run(ROOT, "capabilities")
        assert result.returncode == 0, result.stderr
        cls.payload = json.loads(result.stdout)

    def test_every_parser_command_is_published(self) -> None:
        tree = parser_contract()
        top_level = {path for path in tree if " " not in path}
        self.assertEqual(sorted(top_level - set(self.payload["commands"])), [])

    def test_every_parser_flag_is_published_for_its_command(self) -> None:
        published = self.payload["flags"]
        problems = []
        for path, flags in parser_contract().items():
            missing = sorted(flags - set(published.get(path) or []))
            if missing:
                problems.append(f"{path}: missing {missing}")
        self.assertEqual(problems, [])

    def test_the_flags_that_drifted_are_published(self) -> None:
        check = set(self.payload["flags"]["check"])
        self.assertTrue({"--task", "--agent", "--no-commands"} <= check, sorted(check))
        self.assertIn("--review", set(self.payload["flags"]["task next"]))

    def test_a_subcommand_path_carries_its_own_flags(self) -> None:
        self.assertIn("--set", set(self.payload["flags"]["setup"]))
        self.assertIn("--reason", set(self.payload["flags"]["task request-changes"]))


if __name__ == "__main__":
    unittest.main()
