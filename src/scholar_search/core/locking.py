"""Cross-process locks for metering and browser ownership.

Windows uses ``msvcrt.locking`` and POSIX uses ``fcntl.flock``. A lock file that
cannot be opened is a hard failure: falling back to a process-local lock would
silently drop the cross-process boundary, which is the whole point of this module.
(A read-only home is therefore an error, not a degraded mode.)
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from .errors import ScholarSearchError

_MEMORY_LOCKS: dict[str, threading.Lock] = {}
_MEMORY_GUARD = threading.Lock()


def _memory_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _MEMORY_GUARD:
        return _MEMORY_LOCKS.setdefault(key, threading.Lock())


def _ensure_byte(handle: IO[bytes]) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)


def _try_lock(handle: IO[bytes]) -> None:
    # ``sys.platform`` rather than ``os.name``: mypy narrows on the former, so
    # each CI platform analyses only its own branch.
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def interprocess_lock(path: Path, *, timeout_s: float = 60.0) -> Iterator[None]:
    """Hold an exclusive cross-process lock.

    A lock that cannot be created is a hard failure: falling back to a
    process-local lock would silently drop the cross-process safety boundary.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    _ensure_byte(handle)

    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                _try_lock(handle)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    # A plain TimeoutError is not a ScholarSearchError, so callers
                    # that catch project errors let it escape as a traceback.
                    raise ScholarSearchError(f"lock timeout: {path}") from None
                time.sleep(0.05)
        yield
    finally:
        with contextlib.suppress(OSError):
            _unlock(handle)
        handle.close()
