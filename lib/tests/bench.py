#!/usr/bin/env python3
"""Where does the test time go on THIS machine?  (takes about 20-40 seconds)

    python lib/tests/bench.py
    python lib/tests/bench.py --tmp C:\\ai-test-tmp   # build everything in another folder (e.g. an antivirus-excluded one)
    python lib/tests/bench.py --profile               # also show where one `ai.py` call spends its time

It measures the building blocks every test is made of and prints one table:
how big the copied workspace is, what starting a process costs (Python, git,
`ai.py`), what a Python source-compile costs without .pyc files, and what one
per-test workspace copy costs. Paste the output back; it decides what to fix next.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import _workspace as ws

REPS = 5


class _Case:
    """Minimal stand-in for a unittest case: collects cleanups."""

    def __init__(self) -> None:
        self.cleanups = []

    def addCleanup(self, func, *args) -> None:
        self.cleanups.append((func, args))

    def close(self) -> None:
        for func, args in reversed(self.cleanups):
            func(*args)


def median_ms(func, reps: int = REPS) -> float:
    samples = []
    for _ in range(reps):
        start = time.perf_counter()
        func()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def run(command: list[str], cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, env=env, timeout=120)


def tree_stats(path: Path) -> tuple[int, float]:
    count = size = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            count += 1
            try:
                size += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return count, size / 1024 / 1024


def import_report(python: str, script: Path, cwd: Path, env: dict) -> list[str]:
    """Slowest imports of one `ai.py now --json` call (python -X importtime)."""
    proc = run([python, "-X", "importtime", "-B", str(script), "now", "--json"], cwd=cwd, env=env)
    found = []
    for line in proc.stderr.splitlines():
        match = re.match(r"import time:\s+(\d+)\s+\|\s+(\d+)\s+\|\s+(.*)", line)
        if match:
            found.append((int(match.group(2)) / 1000, match.group(3).strip()))
    found.sort(reverse=True)
    return [f"{ms:7.1f} ms  {name}" for ms, name in found[:14]]


def call_profile(python: str, script: Path, cwd: Path, env: dict) -> list[str]:
    """Top of cProfile for one `ai.py now --json` call, sorted by cumulative time."""
    proc = run([python, "-B", "-m", "cProfile", "-s", "cumtime", str(script), "now", "--json"], cwd=cwd, env=env)
    lines = proc.stdout.splitlines()
    for index, line in enumerate(lines):
        if "function calls" in line:
            return lines[index:index + 34]
    return ["(no profile output)"] + proc.stderr.splitlines()[:5]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tmp", metavar="DIR", help="folder to build the throwaway workspaces in")
    parser.add_argument("--profile", action="store_true", help="also profile one ai.py call")
    args = parser.parse_args()
    if args.tmp:
        os.makedirs(args.tmp, exist_ok=True)
        for key in ("TMPDIR", "TEMP", "TMP"):
            os.environ[key] = args.tmp
        tempfile.tempdir = args.tmp
    rows: list[tuple[str, str]] = []
    extra_blocks: list[tuple[str, list[str]]] = []
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    case = _Case()
    try:
        # 1. what the old tests copied for every single test
        copied = Path(tempfile.mkdtemp(prefix="ai-bench-")) / "project"
        case.addCleanup(ws._force_rmtree, copied.parent)
        start = time.perf_counter()
        shutil.copytree(ws.ROOT, copied, ignore=ws.COPY_IGNORE)
        full_copy_ms = (time.perf_counter() - start) * 1000
        files, mb = tree_stats(copied)
        rows.append(("project copied per test", f"{files} files, {mb:.1f} MB"))
        rows.append(("  one full copytree(ROOT) (old cost per test)", f"{full_copy_ms:.0f} ms"))

        # biggest top-level folders, so useless ones can go into EXTRA_IGNORE
        sizes = []
        for entry in sorted(copied.iterdir()):
            if entry.is_dir():
                n, m = tree_stats(entry)
                sizes.append((n, m, entry.name))
            else:
                sizes.append((1, entry.stat().st_size / 1024 / 1024, entry.name))
        for n, m, name in sorted(sizes, reverse=True)[:6]:
            rows.append((f"  folder {name}", f"{n} files, {m:.1f} MB"))

        # 2. process start-up costs
        rows.append(("python -c pass", f"{median_ms(lambda: run([sys.executable, '-c', 'pass'], env=env)):.0f} ms"))
        rows.append(("git --version", f"{median_ms(lambda: run(['git', '--version'])):.0f} ms"))

        # 3. real `ai.py` calls in a throwaway workspace, as the tests make them (-B, no .pyc yet).
        #    `capabilities` loads EVERY command module; `now --json` is a typical single-command call.
        cold = ws.make_workspace(case, "ai-bench-", mode="lite")
        script = str(cold / "ai.py")
        typical = [sys.executable, "-B", script, "now", "--json"]
        everything = [sys.executable, "-B", script, "capabilities"]
        for label, cmd in (("now --json (typical test call)", typical), ("capabilities (loads every module)", everything)):
            probe = run(cmd, cwd=cold, env=env)
            if probe.returncode != 0:
                rows.append((f"ai.py {label}", f"FAILED rc={probe.returncode}: {(probe.stderr or probe.stdout).strip()[:100]}"))
            else:
                rows.append((f"ai.py {label}, no .pyc", f"{median_ms(lambda: run(cmd, cwd=cold, env=env)):.0f} ms"))
        if args.profile:
            extra_blocks.append(("slowest imports of one `now --json` call", import_report(sys.executable, cold / "ai.py", cold, env)))
            extra_blocks.append(("cProfile of one `now --json` call", call_profile(sys.executable, cold / "ai.py", cold, env)))

        # same calls after compiling the sources once (is .pyc the fix?)
        compiled = run([sys.executable, "-m", "compileall", "-q", str(cold / "lib")])
        pycs = sum(1 for _ in (cold / "lib").rglob("*.pyc"))
        rows.append(("compileall exit code / .pyc files written", f"{compiled.returncode} / {pycs}  {compiled.stderr.strip()[:80]}"))
        # Compare the same calls without -B after compileall has populated __pycache__.
        typical_cached = [sys.executable, script, "now", "--json"]
        everything_cached = [sys.executable, script, "capabilities"]
        for label, cmd in (("now --json", typical_cached), ("capabilities", everything_cached)):
            probe = run(cmd, cwd=cold, env=env)
            if probe.returncode == 0:
                rows.append((f"ai.py {label}, WITH .pyc", f"{median_ms(lambda: run(cmd, cwd=cold, env=env)):.0f} ms"))

        # 4. what the new helper costs
        start = time.perf_counter()
        ws._template.cache_clear()
        ws._template(None, ws.GitSpec("main", "Bench", "bench@example.test"), None)
        rows.append(("template build (once per module now)", f"{(time.perf_counter() - start) * 1000:.0f} ms"))
        spec = ws.GitSpec("main", "Bench", "bench@example.test")

        def one_workspace() -> None:
            sub = _Case()
            ws.make_workspace(sub, "ai-bench-", git=spec)
            sub.close()

        rows.append(("per-test copy of the template (new cost per test)", f"{median_ms(one_workspace, 3):.0f} ms"))
    finally:
        case.close()

    width = max(len(name) for name, _ in rows)
    print()
    for name, value in rows:
        print(f"{name.ljust(width)}  {value}")
    for title, lines in extra_blocks:
        print(f"\n--- {title} ---")
        print("\n".join(lines))
    print(f"\nPython {sys.version.split()[0]} on {sys.platform}, {os.cpu_count()} CPUs, temp={tempfile.gettempdir()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
