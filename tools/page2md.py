#!/usr/bin/env python
"""Source-checkout entry point for the packaged converter.

The implementation moved into the package (`scholar_search/page2md.py`) so that a
`pip install wensu` ships it: the MCP hint used to say "run tools/page2md.py", a path that
exists only in this checkout, so every wheel user was told to run a file they did not have
(2026-11-24). Use `wensu page2md --in … --out …` instead; this file stays as a thin shim
because docs and older notes still call it.
"""

from __future__ import annotations

import sys

from scholar_search.page2md import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
