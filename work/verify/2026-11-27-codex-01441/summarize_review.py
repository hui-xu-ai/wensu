"""Summarise local live evidence and regression results; no site calls."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import scholar_search
from scholar_search.core.config import browser_state_paths
from scholar_search.core.policy import PolicyEngine
from scholar_search.core.risk import RiskGuard


def main() -> None:
    home = Path(os.environ["SCHOLAR_SEARCH_HOME"])
    evidence = home / "verification/2026-11-27-codex-0.14.41-p5"

    def read(name: str) -> Any:
        return json.loads((evidence / name).read_text(encoding="utf-8-sig"))

    def save(name: str, value: Any) -> None:
        (evidence / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    normal = read("normal-mdpi-summary.json")
    wiley = read("natural-wiley-summary.json")
    traces = []
    all_navigation_ids = []
    for label, summary in [("normal-mdpi", normal), ("natural-wiley", wiley)]:
        actions = [json.loads(line) for line in (evidence / f"{label}-actions.jsonl").read_text(encoding="utf-8").splitlines()]
        returned = [r for r in actions if r["phase"] == "returned"]
        gotos = [r for r in returned if r["verb"] == "goto"]
        snapshots = [r for r in returned if r["verb"] == "snapshot"]
        all_navigation_ids.extend(r["navigation_id"] for r in gotos)
        payload = summary["response"]
        traces.append({"label": label, "goto_count": len(gotos), "snapshot_count": len(snapshots),
            "goto_navigation_ids_present": all(bool(r.get("navigation_id")) for r in gotos),
            "final_navigation_id_matches_response": gotos[-1]["navigation_id"] == payload.get("navigation_id"),
            "goto_and_capture_tab_ids_match": all(r.get("tab_id") == payload.get("tab_id") for r in snapshots + gotos)})
        if label == "natural-wiley":
            waiting = [r for r in actions if r["verb"] == "await_gate_clear"]
            outcome = next(r for r in waiting if r["phase"] == "returned")
            window_samples = [r["desktop"] for r in waiting if r.get("desktop")]
    expected_hash = "ec603b6b210bb7a20d2cd120a5f591e82f61dc84265fe0bffd115921cd0c7f70"
    inspections = []
    for label in ["springer-saved", "normal-mdpi-convert"]:
        out = evidence / "conversions" / label
        meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
        index = json.loads((out / "index.json").read_text(encoding="utf-8"))
        markdown = " ".join((out / "page.md").read_text(encoding="utf-8").split())
        total = present = 0
        for section in index["sections"]:
            blocks = [p for p in (out / section["file"]).read_text(encoding="utf-8").split("\n\n") if len(p.strip()) > 60]
            total += len(blocks)
            present += sum(" ".join(p.split()) in markdown for p in blocks)
        if label == "springer-saved":
            assert meta["capture_sha256"] == expected_hash
            assert "Fabrication Steps and Error Possibility of Proposed SPR Sensor" in markdown
            assert "Conclusion" in markdown
            assert total == present
        inspections.append({"label": label, "capture_sha256": meta["capture_sha256"],
            "input_changed": meta.get("input_changed"), "coverage": meta["coverage"],
            "index_sections": len(index["sections"]), "tokens": index["total_tokens"],
            "long_blocks_checked": total, "long_blocks_present_in_page_md": present})
    assert all(all(t[key] for key in ["goto_navigation_ids_present", "final_navigation_id_matches_response", "goto_and_capture_tab_ids_match"]) for t in traces)
    assert len(set(all_navigation_ids)) == len(all_navigation_ids) == 4
    source = Path(__file__).resolve().parents[3] / "src/scholar_search"
    installed = Path(scholar_search.__file__).parent
    files = list(source.rglob("*.py"))
    differences = [str(p.relative_to(source)) for p in files if p.relative_to(source).as_posix() != "core/page_nav.py"
        and p.read_text(encoding="utf-8") != (installed / p.relative_to(source)).read_text(encoding="utf-8")]
    baseline = read("installation-baseline.json")
    legacy_unchanged = all(hashlib.sha256(Path(r["path"]).read_bytes()).hexdigest() == r["sha256"]
        for r in baseline[:2] if r["exists"])
    save("user-observations.json", {"date": "2026-11-27", "manual_verification_performed": False,
        "user_reply": "没有手动操作，页面自行变化", "wiley_article_has_html_full_text": False,
        "availability_reply": "刚才这篇文献本身没有网页全文"})
    expected = {"label": "natural-wiley", "doi": "10.1002/pi.2828", "terminal": "partial",
                "reason": "abstract_only", "expected": True,
                "basis": "user confirmed this article has no HTML full text; challenge cleared automatically"}
    old_failures = evidence / "failures.json"
    backup = evidence / "non-ok-outcomes-original.json"
    if old_failures.exists() and not backup.exists():
        backup.write_bytes(old_failures.read_bytes())
    save("expected-partial-outcomes.json", [expected])
    save("failures.json", [])
    result = {"version": scholar_search.__version__, "real_page_read_attempts": 2,
        "normal_terminal": normal["response"]["terminal"], "normal_hash_matches": normal["capture_hash_matches"],
        "wiley_expected_partial": expected, "real_wait": {"ok": outcome["ok"], "cleared": outcome["cleared"],
            "seconds": outcome["seconds"], "before_foreground": window_samples[0].get("foreground_executable"),
            "edge_maximized_foreground_samples": sum(r.get("foreground_executable", "").lower() == "msedge.exe"
                and r.get("foreground_show_cmd") == 3 for r in window_samples),
            "foreground_profile_check": read("foreground-profile-check.json")},
        "action_identity_checks": traces, "navigation_ids_unique": True,
        "conversion_checks": inspections, "source_files": len(files),
        "installed_differences_excluding_private_override": differences,
        "legacy_policy_files_unchanged": legacy_unchanged,
        "quota_before": normal["quota_before"],
        "quota_after": PolicyEngine(state_path=browser_state_paths()[0]).remaining_today,
        "cooldown_until": str(RiskGuard(state_path=browser_state_paths()[1]).cooldown_until())
            if RiskGuard(state_path=browser_state_paths()[1]).cooldown_until() else None,
        "regressions": [{"id": "F41-01", "priority": "P1", "issue": "page storage and cache accidentally became browser-scoped"},
                        {"id": "F41-02", "priority": "P1", "issue": "concurrent initial adoption can overwrite existing shared policy state"},
                        {"id": "F41-03", "priority": "P2", "issue": "status last_job reader and writer use different directories"}]}
    save("review-summary.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
