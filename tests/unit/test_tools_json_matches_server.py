"""`schemas/tools.json` must be exactly what the server advertises.

The file was hand-kept and had drifted — missing `exclude_ut`, the two sort aliases
and `status.brief` — while its own description called it the stable tool surface.
Nothing read it, so nothing failed. It is generated now, and this runs the
generator's own check, so a tool signature cannot move without the file moving too.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_schema_file_matches_the_server() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "dump-tools.py"), "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
