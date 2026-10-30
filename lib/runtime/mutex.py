"""runtime.mutex: split out of the former monolithic ai.py."""

from __future__ import annotations

import contextlib
import os
import time

from lib.core.paths import (
    LOCKS_DIR,
    REGISTRY_MUTEX,
)
from lib.core.fsio import safe_name
from lib.runtime.dirs import ensure_dirs


@contextlib.contextmanager
def registry_mutex(timeout: float = 5.0):
    ensure_dirs()
    started = time.monotonic()
    while True:
        try:
            os.mkdir(REGISTRY_MUTEX)
            break
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(REGISTRY_MUTEX)
            except OSError:
                age = 0
            if age > 30:
                try:
                    os.rmdir(REGISTRY_MUTEX)
                except OSError:
                    pass
                continue
            if time.monotonic() - started > timeout:
                raise TimeoutError("lock registry is busy")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            os.rmdir(REGISTRY_MUTEX)
        except OSError:
            pass


@contextlib.contextmanager
def workspace_state_guard():
    """Serialize state writes against `ai reset --hard`."""
    with registry_mutex():
        reset_lock = os.path.join(LOCKS_DIR, safe_name("project") + ".lock")
        if os.path.exists(reset_lock):
            raise RuntimeError("workspace reset is in progress")
        yield
