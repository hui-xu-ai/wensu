"""Reuse the no-retry, passively observed official MCP test for 0.14.31."""
from pathlib import Path

previous = Path(__file__).resolve().parents[1] / "2026-11-26-codex-01430/live_mcp_check.py"
source = previous.read_text(encoding="utf-8").replace("0.14.30", "0.14.31")
exec(compile(source, str(previous), "exec"), {"__name__": "__main__", "__file__": __file__})
