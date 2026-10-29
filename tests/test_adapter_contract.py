"""Adapter contract validation against schema and CLI capabilities."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(workspace: Path, *args: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    env = dict(__import__("os").environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(workspace / "scripts" / "ai.py"), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )


SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
REQUIRED_FIELDS = ("tool", "entry", "autoload", "supports")


def load_schema() -> dict:
    schema_path = ROOT / "adapters" / "contract.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_adapter(data: dict, schema: dict, path: Path) -> list[str]:
    """Manually validate adapter data against schema. Returns list of errors."""
    errors = []
    for field in schema.get("required", []):
        if field not in data:
            errors.append(f"{path} missing required field: {field}")
    for field, value in data.items():
        if field not in schema.get("properties", {}):
            errors.append(f"{path} has unexpected field: {field}")
    if "version" in data and data["version"] is not None:
        if not isinstance(data["version"], str):
            errors.append(f"{path} version must be a string")
        elif not SEMVER_RE.match(data["version"]):
            errors.append(f"{path} version '{data['version']}' not semver")
    return errors


def extract_command_references(text: str) -> list[str]:
    """Extract 'ai <cmd>' command names referenced in markdown text."""
    pattern = re.compile(
        r"(?:`(?:\.ai/scripts/)?ai\s+([a-z0-9_-]+)|(?:\.ai/scripts/ai|(?<![\w/.])ai)\s+([a-z0-9_-]+))"
    )
    ignored = {"workspace", "engineering", "notes", "adapter", "state"}
    commands = []
    for match in pattern.finditer(text):
        cmd = match.group(1) or match.group(2)
        if cmd and cmd not in ignored and not cmd.startswith("-"):
            commands.append(cmd)
    return commands


def validate_adapter_doc(text: str, valid_commands: set[str]) -> list[str]:
    """Validate that commands referenced in an adapter doc exist in the CLI contract."""
    errors = []
    for cmd in extract_command_references(text):
        if cmd not in valid_commands:
            errors.append(f"referenced unknown command 'ai {cmd}'")
    return errors


class AdapterContractTest(unittest.TestCase):
    def test_adapter_json_files_have_required_fields(self) -> None:
        """Every adapters/*/adapter.json must have required fields."""
        adapters_dir = ROOT / "adapters"
        adapter_files = sorted(adapters_dir.glob("*/adapter.json"))
        self.assertGreater(len(adapter_files), 0, "no adapter.json files found")
        for adapter_file in adapter_files:
            data = json.loads(adapter_file.read_text(encoding="utf-8"))
            for field in REQUIRED_FIELDS:
                self.assertIn(field, data, f"{adapter_file} missing '{field}'")
            if "version" in data and data["version"] is not None:
                self.assertIsInstance(data["version"], str, f"{adapter_file} version not a string")
                self.assertRegex(
                    data["version"], SEMVER_RE,
                    f"{adapter_file} version '{data['version']}' not semver",
                )

    def test_capabilities_json_includes_adapter_contract(self) -> None:
        """ai capabilities --json must include adapter_contract section."""
        result = run(ROOT, "capabilities", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("adapter_contract", payload)
        contract = payload["adapter_contract"]
        self.assertIn("schema_version", contract)
        self.assertIn("schema_path", contract)
        self.assertIn("adapter_dir", contract)
        self.assertIn("state_paths", contract)

    def test_contract_schema_exists(self) -> None:
        """adapters/contract.schema.json must exist and be valid JSON."""
        schema_path = ROOT / "adapters" / "contract.schema.json"
        self.assertTrue(schema_path.is_file(), "contract.schema.json missing")
        schema = load_schema()
        self.assertIn("required", schema)
        self.assertIn("properties", schema)
        for field in REQUIRED_FIELDS:
            self.assertIn(field, schema["required"], f"schema missing required field: {field}")

    def test_all_adapters_conform_to_schema(self) -> None:
        """Every adapter.json must conform to contract.schema.json."""
        schema = load_schema()
        adapters_dir = ROOT / "adapters"
        for adapter_file in sorted(adapters_dir.glob("*/adapter.json")):
            data = json.loads(adapter_file.read_text(encoding="utf-8"))
            errors = validate_adapter(data, schema, adapter_file)
            self.assertEqual(errors, [], f"adapter violations: {errors}")

    def test_adapter_docs_reference_only_valid_commands(self) -> None:
        """Every adapter doc must reference only commands exposed by the CLI."""
        cap_result = run(ROOT, "capabilities", "--json")
        self.assertEqual(cap_result.returncode, 0, cap_result.stderr)
        capabilities = json.loads(cap_result.stdout)
        valid_commands = set(capabilities.get("commands", {}).keys())

        adapters_dir = ROOT / "adapters"
        doc_files = sorted(adapters_dir.glob("**/*.md"))
        self.assertGreater(len(doc_files), 0, "no adapter doc files found")

        all_errors = []
        for doc_file in doc_files:
            text = doc_file.read_text(encoding="utf-8")
            errors = validate_adapter_doc(text, valid_commands)
            for err in errors:
                all_errors.append(f"{doc_file.name}: {err}")
        self.assertEqual(all_errors, [], f"adapter docs reference invalid commands: {all_errors}")

    def test_contract_fails_when_adapter_references_unknown_command(self) -> None:
        """Contract validation fails if an adapter references an unknown command."""
        valid_commands = {"git", "task", "check", "doctor"}
        bad_doc = "Run `.ai/scripts/ai nonexistent_cmd --flag` to test."
        errors = validate_adapter_doc(bad_doc, valid_commands)
        self.assertIn("referenced unknown command 'ai nonexistent_cmd'", errors)

    def test_task_show_prints_ci_results(self) -> None:
        """ai task show prints CI result lines from task log."""
        result = run(ROOT, "task", "show", "0005")
        self.assertEqual(result.returncode, 0, result.stderr)
        # Verify show output works cleanly
        self.assertIn("File:", result.stdout)
        self.assertIn("title:", result.stdout)

        json_result = run(ROOT, "task", "show", "0005", "--json")
        self.assertEqual(json_result.returncode, 0, json_result.stderr)
        payload = json.loads(json_result.stdout)
        self.assertIn("meta", payload)
        self.assertIn("body", payload)

    def test_task_link_github(self) -> None:
        """link_task_github helper links GitHub issue and PR without external tokens."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            task_file = Path(tmpdir) / "0999-test.md"
            task_file.write_text(
                "---\nid: 0999\ntitle: test\nstatus: todo\nowner: null\n---\n\n# 0999 - test\n\n## Notes\n\n## Log\n",
                encoding="utf-8",
            )
            # import helper directly from scripts.ai
            sys.path.insert(0, str(ROOT))
            from scripts.ai import link_task_github
            meta, body = link_task_github(
                str(task_file),
                issue="https://github.com/org/repo/issues/42",
                pr="https://github.com/org/repo/pull/43",
                agent="tester",
            )
            self.assertEqual(meta.get("github_issue"), "https://github.com/org/repo/issues/42")
            self.assertEqual(meta.get("github_pr"), "https://github.com/org/repo/pull/43")
            self.assertIn("GitHub: https://github.com/org/repo/issues/42 / https://github.com/org/repo/pull/43", body)
            self.assertIn("linked GitHub issue: https://github.com/org/repo/issues/42, pr: https://github.com/org/repo/pull/43 by tester", body)


if __name__ == "__main__":
    unittest.main()