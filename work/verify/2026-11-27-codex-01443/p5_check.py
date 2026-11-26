"""Reuse the actual-MCP identity observer for the one requested 0.14.43 read."""
from pathlib import Path

previous = Path(__file__).resolve().parents[1] / "2026-11-27-codex-01441/p5_check.py"
source = previous.read_text(encoding="utf-8").replace("0.14.41", "0.14.43")
exec(compile(source, str(previous), "exec"), {"__name__": "__main__", "__file__": __file__})
