"""Adapter contract validation against schema and CLI capabilities."""

from __future__ import annotations

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


def git(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=workspace, check=True, capture_output=True, text=True, timeout=15
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
        r"(?:`(?:\.ai/)?ai\s+([a-z0-9_-]+)|(?:\.ai/ai|(?<![\w/.])ai)\s+([a-z0-9_-]+))"
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
    def make_workspace(self, *, with_git: bool = False) -> Path:
        temp = Path(tempfile.mkdtemp(prefix="ai-adapter-"))
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
        if with_git:
            git(workspace, "init", "-q", "--initial-branch=develop")
            git(workspace, "config", "user.name", "Adapter Test")
            git(workspace, "config", "user.email", "adapter@example.test")
            git(workspace, "add", "-A")
            git(workspace, "commit", "-qm", "test baseline")
            git(workspace, "branch", "master")
        return workspace

    def check_ok(self, workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
        result = run(workspace, *args)
        self.assertEqual(result.returncode, 0, f"{' '.join(args)}: {result.stderr}{result.stdout}")
        return result

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
        bad_doc = "Run `.ai/ai nonexistent_cmd --flag` to test."
        errors = validate_adapter_doc(bad_doc, valid_commands)
        self.assertIn("referenced unknown command 'ai nonexistent_cmd'", errors)

    def test_task_show_prints_ci_results(self) -> None:
        """ai task show prints CI result lines recorded in the task log."""
        workspace = self.make_workspace()
        task_file = workspace / "tasks" / "active" / "0001-ci-result.md"
        task_file.write_text(
            "---\nid: 0001\ntitle: CI result probe\nstatus: todo\nowner: null\n"
            "priority: low\nspec: null\ncreated: 2026-10-29T00:00:00Z\n"
            "updated: 2026-10-29T00:00:00Z\nlock: null\ndepends_on: []\nbranch: null\n---\n\n"
            "# 0001 - CI result probe\n\n## Log\n\n"
            "- 2026-10-29T01:00:00Z CI: https://ci.example/run/7 passed\n",
            encoding="utf-8",
        )
        shown = self.check_ok(workspace, "task", "show", "0001")
        self.assertIn("CI results:", shown.stdout)
        self.assertIn("https://ci.example/run/7 passed", shown.stdout)

        payload = json.loads(self.check_ok(workspace, "task", "show", "0001", "--json").stdout)
        self.assertEqual(len(payload["ci_results"]), 1)
        self.assertIn("CI: https://ci.example/run/7 passed", payload["ci_results"][0])

    def test_git_commit_records_ci_result(self) -> None:
        """ai git commit --ci appends the CI result to the task log."""
        workspace = self.make_workspace(with_git=True)
        self.check_ok(workspace, "task", "new", "CI recording", "--no-spec")
        self.check_ok(workspace, "task", "claim", "0001", "--agent", "alice")
        self.check_ok(
            workspace, "git", "start", "--task", "0001", "--agent", "alice", "--type", "feature",
        )
        (workspace / "sample.txt").write_text("change\n", encoding="utf-8")
        git(workspace, "add", "sample.txt")
        self.check_ok(
            workspace, "git", "commit", "--task", "0001", "--agent", "alice",
            "--type", "test", "--message", "add sample file",
            "--ci", "https://ci.example/run/8 passed",
        )

        task_file = next((workspace / "tasks" / "active").glob("0001-*.md"))
        self.assertIn("CI: https://ci.example/run/8 passed", task_file.read_text(encoding="utf-8"))
        shown = self.check_ok(workspace, "task", "show", "0001")
        self.assertIn("CI results:", shown.stdout)
        self.assertIn("https://ci.example/run/8 passed", shown.stdout)

    def test_task_link_github(self) -> None:
        """link_task_github helper links GitHub issue and PR without external tokens."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_file = Path(tmpdir) / "0999-test.md"
            task_file.write_text(
                "---\nid: 0999\ntitle: test\nstatus: todo\nowner: null\n---\n\n# 0999 - test\n\n## Notes\n\n## Log\n",
                encoding="utf-8",
            )
            # import helper directly from lib.tasks.links
            sys.path.insert(0, str(ROOT))
            from lib.tasks.links import link_task_github
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