"""Inspect the one saved real read; no MCP, browser or policy-state mutation."""
from __future__ import annotations

import json
import os
from pathlib import Path

import scholar_search


def main() -> None:
    assert scholar_search.__version__ == "0.14.43"
    home = Path(os.environ["SCHOLAR_SEARCH_HOME"])
    evidence = home / "verification/2026-11-27-codex-0.14.43-p5"
    summary = json.loads((evidence / "two-goto-mdpi-summary.json").read_text(encoding="utf-8"))
    actions = [json.loads(line) for line in (evidence / "two-goto-mdpi-actions.jsonl").read_text(encoding="utf-8").splitlines()]
    returned = [row for row in actions if row["phase"] == "returned"]
    gotos = [row for row in returned if row["verb"] == "goto"]
    captures = [row for row in returned if row["verb"] == "snapshot"]
    assert len(gotos) == 2 and captures
    first, article = (row["navigation_id"] for row in gotos)
    assert first and article and first != article
    assert all(row["navigation_id"] == article for row in captures)
    assert all(row["tab_id"] == gotos[-1]["tab_id"] for row in gotos + captures)
    payload = summary["response"]
    source = Path(__file__).resolve().parents[3] / "src/scholar_search"
    installed = Path(scholar_search.__file__).parent
    files = list(source.rglob("*.py"))
    differences = [str(p.relative_to(source)) for p in files
        if p.relative_to(source).as_posix() != "core/page_nav.py"
        and p.read_text(encoding="utf-8") != (installed / p.relative_to(source)).read_text(encoding="utf-8")]
    worker = "background-0.14.43.js"
    worker_matches = (source.parents[1] / "extension" / worker).read_text(encoding="utf-8") == (
        home / "browser/extension" / worker).read_text(encoding="utf-8")
    result = {"version": scholar_search.__version__, "real_page_read_attempts": 1,
        "doi": payload["doi"], "bridge_build": summary["bridge_build"],
        "navigation_trace": [{"step": "first goto", "navigation_id": first, "tab_id": gotos[0]["tab_id"]},
                             {"step": "article goto", "navigation_id": article, "tab_id": gotos[1]["tab_id"]},
                             *[{"step": "snapshot", "navigation_id": row["navigation_id"], "tab_id": row["tab_id"]} for row in captures]],
        "capture_matches_article_navigation": True,
        "capture_matches_first_navigation": False,
        "kernel_read_nav_selection": "first non-empty navigation_id, from next(... for outcome in outcomes)",
        "actual_response": {key: payload.get(key) for key in ["terminal", "stage", "reason", "capture_navigation",
            "declared_doi", "captured_url", "final_url", "navigation_id", "mhtml_path", "bytes", "quota_charged", "job_id"]},
        "quota_before": summary["quota_before"], "quota_after": summary["quota_after"],
        "source_files": len(files), "installed_differences_excluding_private_override": differences,
        "worker_disk_matches_reviewed_source": worker_matches}
    (evidence / "identity-review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
