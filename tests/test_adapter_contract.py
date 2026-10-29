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


if __name__ == "__main__":
    unittest.main()