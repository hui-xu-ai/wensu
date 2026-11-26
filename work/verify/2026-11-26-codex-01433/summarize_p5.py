"""Summarise saved P5 evidence; no MCP or browser calls, no product-state writes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from scholar_search.core.policy import PolicyEngine
from scholar_search.core.risk import RiskGuard


def main() -> None:
    root = Path(os.environ["SCHOLAR_SEARCH_HOME"]) / "verification/2026-11-26-codex-0.14.33-p5"

    def read(name: str) -> Any:
        return json.loads((root / name).read_text(encoding="utf-8"))

    def write(name: str, value: Any) -> None:
        temporary = root / (name + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(root / name)

    plan = read("batch-plan.json")
    rows: list[dict[str, Any]] = []
    acquisition_failures: list[dict[str, Any]] = []
    conversion_failures: list[dict[str, Any]] = []
    for item in plan["planned"]:
        label = item["label"]
        summary = read(f"{label}-summary.json")
        assert not summary.get("test_error"), summary
        response = summary["response"]
        row = {**item, **{k: response.get(k) for k in ["terminal", "stage", "reason", "identity",
               "quota_charged", "job_id", "capture_sha256", "mhtml_path", "captured_url"]},
               "capture_hash_matches": summary.get("capture_hash_matches")}
        if response.get("mhtml_path"):
            actual = hashlib.sha256(Path(response["mhtml_path"]).read_bytes()).hexdigest()
            assert actual == response["capture_sha256"]
        if response.get("terminal") == "ok":
            converted = read(f"convert-{label}-summary.json")
            assert not converted.get("test_error"), converted
            conversion = converted["conversion"]
            assert conversion["input_unchanged"] and not conversion.get("input_changed")
            assert conversion["capture_sha256"] == conversion["meta_capture_sha256"] == response["capture_sha256"]
            row["conversion"] = conversion
            row["conversion_page_md"] = converted["response"].get("page_md")
            row["conversion_quality"] = "structure_checked_with_stated_limits"
            if label == "batch-springer-1":
                inspection = read("convert-batch-springer-1-inspection.json")
                assert inspection["finding"]["severity"] == "P1"
                row["conversion_quality"] = "rejected_body_truncated"
                conversion_failures.append({**item, "capture_sha256": response["capture_sha256"],
                    "phase": "conversion_validation", "audit_result": "rejected",
                    "reason": "body_truncated_by_unanchored_cited_by", "evidence": inspection["finding"]})
        else:
            acquisition_failures.append({**item, **{k: response.get(k) for k in ["terminal", "stage",
                "reason", "status", "job_id", "evidence", "quota_charged", "capture_sha256"]},
                "phase": "page_read"})
        rows.append(row)
    assert len(rows) == 6
    normal = read("single-mdpi-publish-summary.json")
    warm = read("warm-four-summary.json")
    cost = sum(int(row["quota_charged"] or 0) for row in rows)
    before = normal["quota_before"]
    total_cost = cost + normal["response"]["quota_charged"] + warm["response"]["quota_charged"]
    remaining = PolicyEngine().remaining_today
    old_failure = root / "failures.json"
    backup = root / "failures-before-final-summary.json"
    if old_failure.exists() and not backup.exists():
        backup.write_bytes(old_failure.read_bytes())
    write("failures.json", acquisition_failures)
    write("conversion_failures.json", conversion_failures)
    preflight = read("single-mdpi-summary.json")
    write("preflight-findings.json", {"label": "single-mdpi", "stage": "preflight",
        "test_error": preflight.get("test_error"), "quota_delta": preflight["quota_before"] - preflight["quota_after"],
        "article_read_attempted": False})
    result = {"version": "0.14.33", "planned": 6, "attempted": 6,
        "capture_ok": sum(row["terminal"] == "ok" for row in rows),
        "acquisition_failures": len(acquisition_failures),
        "converted_by_subagents": sum("conversion" in row for row in rows),
        "conversion_quality_failures": len(conversion_failures),
        "batch_quota_charged": cost, "total_run_quota_charged": total_cost,
        "quota_before": before, "quota_after": remaining, "quota_reconciles": before - remaining == total_cost,
        "cooldown_until": str(RiskGuard().cooldown_until()) if RiskGuard().cooldown_until() else None,
        "rows": rows}
    write("batch-summary.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
