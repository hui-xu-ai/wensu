"""Verify the saved single-read result and ID trace; never calls the browser."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def main() -> None:
    home = Path(os.environ["SCHOLAR_SEARCH_HOME"])
    root = home / "verification/2026-11-27-codex-0.14.44-p5"
    summary = json.loads((root / "two-goto-mdpi-summary.json").read_text(encoding="utf-8"))
    events = json.loads((root / "two-goto-mdpi-events.json").read_text(encoding="utf-8"))
    reads = [e for e in events if e["tool"] == "page_read"]
    assert len(reads) == 1 and reads[0]["arguments"] == {"doi": "10.3390/s26041303", "refresh": True}
    build = summary["bridge_build"]
    assert build["worker"] == "background-0.14.44.js" and build["handshake"] == "ok"
    rows = [json.loads(line) for line in (root / "two-goto-mdpi-actions.jsonl").read_text(encoding="utf-8").splitlines()]
    returned = [row for row in rows if row["phase"] == "returned"]
    gotos = [row for row in returned if row["verb"] == "goto"]
    captures = [row for row in returned if row["verb"] == "snapshot"]
    assert len(gotos) == 2 and captures
    first, second = (row["navigation_id"] for row in gotos)
    assert first and second and first != second
    assert all(row["navigation_id"] == second for row in captures)
    assert all(row["tab_id"] == gotos[-1]["tab_id"] for row in gotos + captures)
    payload = summary["response"]
    assert payload["status"] == payload["terminal"] == "ok" and payload["stage"] == "publish"
    assert payload["capture_navigation"] == "match" and payload["navigation_id"] == second
    path = Path(payload["mhtml_path"])
    assert path.resolve() == (home / "pages/10.3390_s26041303/page.mhtml").resolve()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == payload["capture_sha256"]
    result = {"version": "0.14.44", "passed": True, "page_read_attempts": 1, "refresh": True,
              "requested_fields": {k: payload[k] for k in ["status", "capture_navigation", "navigation_id", "mhtml_path"]},
              "first_goto_navigation_id": first, "second_goto_navigation_id": second,
              "snapshot_navigation_ids": [row["navigation_id"] for row in captures],
              "capture_hash_matches": True, "quota_before": summary["quota_before"],
              "quota_after": summary["quota_after"], "page_read_seconds": reads[0]["seconds"]}
    (root / "verified-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
