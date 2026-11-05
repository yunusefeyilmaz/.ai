"""Existing-repo onboarding: adopt commits the baseline, setup lands on develop.

On an existing repository `ai adopt` used to leave `.ai/` and `.gitignore`
untracked, so the first `ai start` refused with a dirty tree, and `ai git setup`
left HEAD on production while `develop` started behind it. Both are fixed here
and these tests reproduce the real subfolder install (a host repo with `.ai/`
inside it).
"""

from __future__ import annotations

from _workspace import copy_project

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_COPY_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", ".mypy_cache", ".ruff_cache", "*.pyc", "*.pyo",
)
# Throwaway runs leave test workspaces under runtime/temp; never copy them.
_RUNTIME_ROOT = (ROOT / "runtime").resolve()


def COPY_IGNORE(directory: str, names: list[str]) -> set[str]:
    ignored = set(_COPY_IGNORE(directory, names))
    if Path(directory).resolve() == _RUNTIME_ROOT:
        ignored.add("temp")
    return ignored
BASELINE_MESSAGE = "chore: add ai workspace baseline"


def run(host: Path, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(host / ".ai" / "ai.py"), *args],
        cwd=str(host),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )


def git(host: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(host),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def git_ok(host: Path, *args: str) -> str:
    result = git(host, *args)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


class OnboardingTest(unittest.TestCase):
    def make_host(self, init_ai: bool = True) -> Path:
        """A project that already has Git history and then receives `.ai/`."""
        temp = Path(tempfile.mkdtemp(prefix="ai-onboarding-"))
        self.addCleanup(shutil.rmtree, temp, True)
        host = temp / "project"
        host.mkdir()
        (host / "README.md").write_text("# Host project\n", encoding="utf-8")
        (host / "app.py").write_text("print('host')\n", encoding="utf-8")
        (host / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        self.assertEqual(git(host, "init", "-q", "--initial-branch", "master").returncode, 0)
        git_ok(host, "config", "user.name", "Onboarding Test")
        git_ok(host, "config", "user.email", "onboarding@example.test")
        git_ok(host, "add", "-A")
        git_ok(host, "commit", "-qm", "product baseline")
        if init_ai:
            self.install_ai(host)
        return host

    def install_ai(self, host: Path) -> None:
        copy_project(host / ".ai")
        # Throwaway runs leave test workspaces under runtime/temp; never copy them.
        shutil.rmtree(host / ".ai" / "runtime" / "temp", ignore_errors=True)
        config = host / ".ai" / "config" / "workspace.json"
        data = json.loads(config.read_text(encoding="utf-8"))
        data["checks"] = []
        config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def head_branch(self, host: Path) -> str:
        return git_ok(host, "rev-parse", "--abbrev-ref", "HEAD")

    def is_ancestor(self, host: Path, ancestor: str, descendant: str) -> bool:
        return git(host, "merge-base", "--is-ancestor", ancestor, descendant).returncode == 0

    # --- `ai adopt` ---------------------------------------------------------

    def test_adopt_commits_the_workspace_baseline_and_leaves_a_clean_tree(self) -> None:
        host = self.make_host()
        production = git_ok(host, "rev-parse", "master")

        adopted = run(host, "adopt")

        self.assertEqual(adopted.returncode, 0, adopted.stderr + adopted.stdout)
        self.assertEqual(git_ok(host, "status", "--porcelain"), "", "the tree must be clean after adopt")
        self.assertEqual(self.head_branch(host), "develop")
        self.assertEqual(git_ok(host, "log", "-1", "--format=%s"), BASELINE_MESSAGE)
        self.assertIn(".ai/AGENTS.md", git_ok(host, "ls-files", "--", ".ai/AGENTS.md"))
        self.assertIn(".gitignore", git_ok(host, "ls-files", "--", ".gitignore"))
        self.assertTrue(
            self.is_ancestor(host, production, "develop"),
            "the integration branch must contain production's existing commit",
        )
        # Product files are never committed by adopt.
        self.assertEqual(git_ok(host, "status", "--porcelain", "--", "README.md", "app.py"), "")

    def test_adopt_ignores_generated_adapters(self) -> None:
        host = self.make_host()

        self.assertEqual(run(host, "adopt").returncode, 0)

        tracked = git_ok(host, "ls-files")
        self.assertNotIn("AGENTS.md", tracked.splitlines())
        self.assertNotIn("CLAUDE.md", tracked.splitlines())
        self.assertEqual(git_ok(host, "status", "--porcelain"), "")

    def test_a_second_adopt_adds_no_commit_and_stays_clean(self) -> None:
        host = self.make_host()
        self.assertEqual(run(host, "adopt").returncode, 0)
        first = git_ok(host, "rev-parse", "HEAD")

        again = run(host, "adopt")

        self.assertEqual(again.returncode, 0, again.stderr + again.stdout)
        self.assertEqual(git_ok(host, "rev-parse", "HEAD"), first)
        self.assertEqual(git_ok(host, "status", "--porcelain"), "")
        self.assertEqual(
            len([line for line in git_ok(host, "log", "--format=%s").splitlines() if line == BASELINE_MESSAGE]),
            1,
        )

    def test_adopt_check_does_not_commit(self) -> None:
        host = self.make_host()
        before = git_ok(host, "rev-parse", "HEAD")
        self.assertEqual(self.head_branch(host), "master")

        checked = run(host, "adopt", "--check")

        self.assertEqual(checked.returncode, 1, "the workspace is not adopted yet")
        self.assertEqual(git_ok(host, "rev-parse", "HEAD"), before)
        self.assertEqual(self.head_branch(host), "master")

    def test_a_failed_baseline_commit_prints_the_exact_commands(self) -> None:
        host = self.make_host()
        git_ok(host, "config", "--unset", "user.name")
        git_ok(host, "config", "--unset", "user.email")
        empty_home = Path(tempfile.mkdtemp(prefix="ai-no-identity-"))
        self.addCleanup(shutil.rmtree, empty_home, True)
        env = {
            "HOME": str(empty_home),
            "USERPROFILE": str(empty_home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(empty_home / "gitconfig"),
        }

        adopted = run(host, "adopt", env_extra=env)

        self.assertEqual(adopted.returncode, 1, adopted.stderr + adopted.stdout)
        output = adopted.stdout + adopted.stderr
        self.assertIn("git add -A --", output)
        self.assertIn(f'git commit -m "{BASELINE_MESSAGE}"', output)
        self.assertIn("git checkout develop", output)
        self.assertEqual(git_ok(host, "diff", "--cached", "--name-only"), "", "nothing may stay staged")

    def test_adopt_without_git_still_succeeds(self) -> None:
        temp = Path(tempfile.mkdtemp(prefix="ai-onboarding-nogit-"))
        self.addCleanup(shutil.rmtree, temp, True)
        host = temp / "project"
        host.mkdir()
        (host / ".gitignore").write_text(".ai/\n", encoding="utf-8")
        self.install_ai(host)

        adopted = run(host, "adopt")

        self.assertEqual(adopted.returncode, 0, adopted.stderr + adopted.stdout)
        ignore = (host / ".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("\n.ai/\n", "\n" + ignore)

    # --- `ai git setup` -----------------------------------------------------

    def test_setup_ends_with_head_on_develop(self) -> None:
        host = self.make_host()

        setup = run(host, "git", "setup")

        self.assertEqual(setup.returncode, 0, setup.stderr + setup.stdout)
        self.assertEqual(self.head_branch(host), "develop")
        self.assertEqual(git_ok(host, "rev-parse", "develop"), git_ok(host, "rev-parse", "master"))

    def test_setup_fast_forwards_a_stale_develop_to_production(self) -> None:
        host = self.make_host()
        git_ok(host, "branch", "develop")  # develop starts at the first commit
        (host / "later.txt").write_text("newer production work\n", encoding="utf-8")
        git_ok(host, "add", "later.txt")
        git_ok(host, "commit", "-qm", "later production work")

        setup = run(host, "git", "setup")

        self.assertEqual(setup.returncode, 0, setup.stderr + setup.stdout)
        self.assertEqual(self.head_branch(host), "develop")
        self.assertEqual(git_ok(host, "rev-parse", "develop"), git_ok(host, "rev-parse", "master"))
        self.assertTrue(self.is_ancestor(host, "master", "develop"))

    def test_setup_refuses_to_rewrite_diverged_branches(self) -> None:
        host = self.make_host()
        git_ok(host, "checkout", "-q", "-b", "develop")
        (host / "feature.txt").write_text("work on develop\n", encoding="utf-8")
        git_ok(host, "add", "feature.txt")
        git_ok(host, "commit", "-qm", "develop work")
        git_ok(host, "checkout", "-q", "master")
        (host / "later.txt").write_text("work on production\n", encoding="utf-8")
        git_ok(host, "add", "later.txt")
        git_ok(host, "commit", "-qm", "production work")
        develop_before = git_ok(host, "rev-parse", "develop")

        setup = run(host, "git", "setup")

        self.assertEqual(setup.returncode, 1, setup.stderr + setup.stdout)
        self.assertIn("diverged", setup.stderr)
        self.assertIn("git merge master", setup.stderr)
        self.assertEqual(git_ok(host, "rev-parse", "develop"), develop_before)

    def test_existing_repo_flow_adopt_then_setup_is_clean_on_develop(self) -> None:
        host = self.make_host()
        production = git_ok(host, "rev-parse", "master")

        self.assertEqual(run(host, "adopt").returncode, 0)
        setup = run(host, "git", "setup")

        self.assertEqual(setup.returncode, 0, setup.stderr + setup.stdout)
        self.assertEqual(self.head_branch(host), "develop")
        self.assertEqual(git_ok(host, "status", "--porcelain"), "")
        self.assertTrue(self.is_ancestor(host, production, "develop"))


if __name__ == "__main__":
    unittest.main()
