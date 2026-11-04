#!/usr/bin/env python3
"""Run the CLI tests in parallel: one process per test module.

    python lib/tests/run.py            # all modules, one worker per CPU
    python lib/tests/run.py -j 12       # explicit worker count
    python lib/tests/run.py test_doctor test_board   # selected modules

Each test builds its own temp workspace, so modules are independent. Output is
quiet on success; failing modules print their full unittest report. Exit code
is 1 if any module failed. `python -m unittest discover -s lib/tests` still
works (serially).

    python lib/tests/run.py --coverage  # needs `pip install coverage`
    python -m coverage combine && python -m coverage report

Coverage is opt-in because the suite shells out to `ai.py`; measuring it means
running each module under `coverage run --parallel-mode`.

Each module has a timeout so a deadlocked subprocess cannot make the whole suite
appear to run forever. Increase it with `--timeout` for unusually slow machines.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def run_module(name: str, coverage: bool = False, timeout: int = 300) -> tuple[str, int, str, float]:
    start = time.time()
    env = dict(
        os.environ,
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    command = [sys.executable, "-m", "unittest", name, "-q"]
    if coverage:
        command = [
            sys.executable, "-m", "coverage", "run", "--parallel-mode",
            "--source=lib", "-m", "unittest", name, "-q",
        ]
    try:
        proc = subprocess.run(
            command,
            cwd=HERE,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        return name, 124, f"timed out after {timeout}s\n{output}", time.time() - start
    return name, proc.returncode, proc.stdout + proc.stderr, time.time() - start


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("modules", nargs="*")
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=min(8, os.cpu_count() or 1),
        help="maximum test modules to run at once (default: min(8, CPU count))",
    )
    parser.add_argument("--timeout", type=int, default=300, help="per-module timeout in seconds")
    parser.add_argument("--coverage", action="store_true", help="run each module under `coverage run`")
    args = parser.parse_args()
    if args.coverage:
        try:
            import coverage as _coverage  # noqa: F401
        except ImportError:
            print("--coverage needs `pip install coverage`", file=sys.stderr)
            return 1

    names = args.modules or sorted(f[:-3] for f in os.listdir(HERE) if f.startswith("test_") and f.endswith(".py"))
    # slowest-first keeps all workers busy until the end
    names.sort(key=lambda n: -os.path.getsize(os.path.join(HERE, n + ".py")))
    started = time.time()
    failed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for name, code, output, seconds in pool.map(
            lambda module: run_module(module, args.coverage, args.timeout), names
        ):
            status = "ok  " if code == 0 else "FAIL"
            print(f"{status} {name} ({seconds:.1f}s)")
            if code != 0:
                failed += 1
                print(output)
    print(f"{len(names)} module(s), {failed} failed, {time.time() - started:.1f}s wall (-j {args.jobs})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
