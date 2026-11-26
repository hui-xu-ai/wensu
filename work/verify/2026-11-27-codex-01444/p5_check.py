"""Reuse the no-retry official MCP identity observer for one 0.14.44 read."""
from pathlib import Path

previous = Path(__file__).resolve().parents[1] / "2026-11-27-codex-01441/p5_check.py"
source = previous.read_text(encoding="utf-8").replace("0.14.41", "0.14.44")
exec(compile(source, str(previous), "exec"), {"__name__": "__main__", "__file__": __file__})
