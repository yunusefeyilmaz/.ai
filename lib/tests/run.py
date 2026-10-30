#!/usr/bin/env python3
"""Run the CLI tests in parallel: one process per test module.

    python lib/tests/run.py            # all modules, one worker per CPU
    python lib/tests/run.py -j 8       # explicit worker count
    python lib/tests/run.py test_doctor test_board   # selected modules

Each test builds its own temp workspace, so modules are independent. Output is
quiet on success; failing modules print their full unittest report. Exit code
is 1 if any module failed. `python -m unittest discover -s lib/tests` still
works (serially).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def run_module(name: str) -> tuple[str, int, str, float]:
    start = time.time()
    env = dict(os.environ, PYTHONUTF8="1")
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", name, "-q"],
        cwd=HERE, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    return name, proc.returncode, proc.stdout + proc.stderr, time.time() - start


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("modules", nargs="*")
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()

    names = args.modules or sorted(f[:-3] for f in os.listdir(HERE) if f.startswith("test_") and f.endswith(".py"))
    # slowest-first keeps all workers busy until the end
    names.sort(key=lambda n: -os.path.getsize(os.path.join(HERE, n + ".py")))
    started = time.time()
    failed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for name, code, output, seconds in pool.map(run_module, names):
            status = "ok  " if code == 0 else "FAIL"
            print(f"{status} {name} ({seconds:.1f}s)")
            if code != 0:
                failed += 1
                print(output)
    print(f"{len(names)} module(s), {failed} failed, {time.time() - started:.1f}s wall (-j {args.jobs})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
