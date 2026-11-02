"""runtime.mutex: the workspace-wide state registry lock.

The lock is an OS advisory lock on a file, not a directory whose age is
guessed. Two consequences matter:

* a crashed process releases it automatically (the kernel drops the lock),
  so a dead holder cannot stall every state command for 30 seconds;
* a slow-but-alive holder cannot be "stolen" after a fixed age, so two
  processes never believe they both hold it.

A directory-based mutex is kept as a fallback for filesystems where advisory
locking is unavailable.
"""

from __future__ import annotations

import contextlib
import os
import time

from lib.core.paths import REGISTRY_MUTEX
from lib.core.fsio import lock_path
from lib.runtime.dirs import ensure_dirs

_MUTEX_FILE = REGISTRY_MUTEX  # advisory lock file; no `.lock` suffix so it is not a lease
_FALLBACK_STALE_SECONDS = 5.0
_ADVISORY = True

# Re-entrancy guard: a single-threaded CLI may nest registry_mutex() calls
# (e.g. workspace_state_guard() -> acquire_lock()). Tracking the holding state
# lets nested calls skip the OS lock and just yield.
_holding_mutex = False

if os.name == "nt":  # pragma: no cover - exercised on Windows CI
    import msvcrt

    def _try_lock(descriptor: int) -> bool:
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:  # pragma: no cover - exercised on POSIX CI
    try:
        import fcntl
    except ImportError:  # unlikely, but keep the fallback reachable
        _ADVISORY = False
    else:
        def _try_lock(descriptor: int) -> bool:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                return False

        def _unlock(descriptor: int) -> None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass


def _open_mutex_file() -> int:
    os.makedirs(os.path.dirname(_MUTEX_FILE), exist_ok=True)
    if os.path.isdir(_MUTEX_FILE):
        # Upgrade from the old directory-based mutex left by a crash.
        try:
            os.rmdir(_MUTEX_FILE)
        except OSError:
            pass
    descriptor = os.open(_MUTEX_FILE, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.fstat(descriptor).st_size == 0:
            # msvcrt.locking() needs a byte to lock.
            os.write(descriptor, b"ai")
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError:
        pass
    return descriptor


@contextlib.contextmanager
def _directory_mutex(timeout: float):
    """Fallback for filesystems without advisory locking."""
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
                age = 0.0
            if age > _FALLBACK_STALE_SECONDS:
                try:
                    os.rmdir(REGISTRY_MUTEX)
                    continue
                except OSError:
                    # A stale-but-unremovable directory must not spin forever;
                    # fall through to the timeout check below.
                    pass
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
def registry_mutex(timeout: float = 10.0):
    """Serialize every write to shared workspace state."""
    global _holding_mutex
    # Re-entrant: same thread already holds the mutex, just yield.
    if _holding_mutex:
        yield
        return
    if not _ADVISORY:
        with _directory_mutex(timeout):
            yield
        return
    try:
        descriptor = _open_mutex_file()
    except OSError:
        with _directory_mutex(timeout):
            yield
        return
    held = False
    started = time.monotonic()
    try:
        while not _try_lock(descriptor):
            if time.monotonic() - started > timeout:
                raise TimeoutError("lock registry is busy")
            time.sleep(0.02)
        held = True
        _holding_mutex = True
        yield
    finally:
        if held:
            _unlock(descriptor)
        _holding_mutex = False
        os.close(descriptor)


@contextlib.contextmanager
def workspace_state_guard():
    """Serialize state writes against `ai reset --hard`."""
    with registry_mutex():
        reset_lock = lock_path("project")
        if os.path.exists(reset_lock):
            raise RuntimeError("workspace reset is in progress")
        yield
