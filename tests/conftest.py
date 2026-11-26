"""Make ``tests/support.py`` importable from every test module, and keep tests in a sandbox."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Browser-scoped state (the lock that serialises the browser) is machine-wide by design
# (ADR 0029), which would otherwise make every test run write into the real user directory and
# contend with a running instance. Point it at a throwaway directory for the whole session.
os.environ.setdefault(
    "SCHOLAR_SEARCH_BROWSER_STATE", tempfile.mkdtemp(prefix="wensu-test-browser-state-")
)
