"""Version-pinned official MCP observer; updated accounting for browser-scoped policy state."""
from pathlib import Path

previous = Path(__file__).resolve().parents[1] / "2026-11-26-codex-01433/p5_check.py"
source = previous.read_text(encoding="utf-8").replace("0.14.33", "0.14.41")
source = source.replace("2026-11-26-codex-0.14.41-p5", "2026-11-27-codex-0.14.41-p5")
import_line = "    from scholar_search.core.policy import PolicyEngine\n"
assert source.count(import_line) == 1
source = source.replace(import_line, "    from scholar_search.core.config import browser_state_paths\n" + import_line)
source = source.replace("PolicyEngine()", "PolicyEngine(state_path=browser_state_paths()[0])")
source = source.replace("RiskGuard()", "RiskGuard(state_path=browser_state_paths()[1])")
cap_line = '                    result["await_gate_clear_advertised"] = "await_gate_clear" in (build.get("capabilities") or [])'
assert source.count(cap_line) == 1
source = source.replace(cap_line, cap_line + '\n                    assert result["await_gate_clear_advertised"], build')
source = source.replace('if action.verb in {"goto", "await_gate_clear"}:',
    'if action.verb in {"goto", "await_gate_clear"} or (action.verb == "snapshot" and not action.params.get("token")):')
source = source.replace('"tab_id", "kept", "navigation_attempts"]',
    '"tab_id", "navigation_id", "kept", "navigation_attempts"]')
marker = '                        result["capture_hash_matches"] = actual == payload.get("capture_sha256")'
assert source.count(marker) == 1
source = source.replace(marker, marker + '\n                    if payload.get("terminal") == "ok":\n                        result["post_status"] = await call("status", {"brief": True})')
exec(compile(source, str(previous), "exec"), {"__name__": "__main__", "__file__": __file__})
