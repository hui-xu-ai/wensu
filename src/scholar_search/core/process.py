"""Whether a pid names a live process — asked of the kernel, not inferred from a signal.

The endpoint files the native host leaves behind (`host/hosts/bridge-<pid>.json`) outlive the
process that wrote them, and every one of them costs a connect timeout when the bridge looks for a
host: measured 2026-11-25, fourteen of them at 605 ms each put **8.5 s** in front of every search
before anything reached the browser. Deciding "this file cannot come back" needs a real liveness
answer, so it lives here, one implementation, used by the doctor and by the bridge.
"""

from __future__ import annotations

import os
from typing import Any, cast


def process_alive(pid: object) -> bool:
    """Whether `pid` names a live process. Windows needs OpenProcess, not `os.kill(pid, 0)`.

    On Windows `os.kill(pid, 0)` is not a probe: signal 0 goes through TerminateProcess, so it
    can either lie or kill. Query the handle instead (measured 2026-11-24: the host was alive
    and `os.kill` said otherwise).
    """

    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        # Viewed as `Any`: `windll` only exists on Windows, and CI type-checks on Linux (the
        # same platform-gated-attribute problem `msvcrt` had — see `core/browser.py`).
        kernel32 = cast(Any, ctypes).windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
