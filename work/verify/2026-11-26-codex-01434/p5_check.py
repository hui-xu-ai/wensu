"""Reuse the reviewed, no-retry official MCP observer for the new release."""
from pathlib import Path

previous = Path(__file__).resolve().parents[1] / "2026-11-26-codex-01433/p5_check.py"
source = previous.read_text(encoding="utf-8").replace("0.14.33", "0.14.34")
marker = '                    result["await_gate_clear_advertised"] = "await_gate_clear" in (build.get("capabilities") or [])'
assert source.count(marker) == 1
source = source.replace(marker, marker + '\n                    assert result["await_gate_clear_advertised"], build')
exec(compile(source, str(previous), "exec"), {"__name__": "__main__", "__file__": __file__})
