"""Offline concurrency checks; no bridge endpoint is opened."""
from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import os
import tempfile
import threading
import time
from pathlib import Path

import scholar_search
from scholar_search.core.locking import interprocess_lock


def lock_trial(root: Path, shared_path: bool) -> dict[str, int]:
    start = threading.Barrier(2)
    guard = threading.Lock()
    state = {"active": 0, "maximum": 0}
    def worker(index: int) -> None:
        path = root / ("shared" if shared_path else f"job-{index}") / "browser.lock"
        start.wait(5)
        with interprocess_lock(path, timeout_s=5):
            with guard:
                state["active"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
            time.sleep(0.1)
            with guard:
                state["active"] -= 1
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        list(pool.map(worker, range(2)))
    return {"maximum_inside_critical_section": state["maximum"]}


def main() -> None:
    assert scholar_search.__version__ == "0.14.30"
    prior = Path(__file__).resolve().parents[1] / "2026-11-26-codex-01429/verify_installed.py"
    spec = importlib.util.spec_from_file_location("offline_fixtures", prior)
    assert spec and spec.loader
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    with tempfile.TemporaryDirectory(prefix="wensu-030-concurrency-") as directory:
        root = Path(directory)
        shared = lock_trial(root / "locks", True)
        separate = lock_trial(root / "other-locks", False)
        service = helpers.fixture_service(root / "duplicate", [*helpers.nav(),
            {"verb": "sleep"}, helpers.capture(helpers.ARTICLE)])
        original_get = service._page_cache_get
        barrier = threading.Barrier(2)
        def read_before_lock(url: str):
            value = original_get(url)
            barrier.wait(5)
            return value
        service._page_cache_get = read_before_lock
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(service.read_page, doi=helpers.DOI) for _ in range(2)]
            answers = [future.result(12) for future in futures]
        duplicate = {"statuses": [a.get("status") for a in answers],
            "reported_costs": [a.get("quota_charged") for a in answers],
            "cached_flags": [bool(a.get("cached")) for a in answers],
            "synthetic_quota_used": service._policy.used_today,
            "same_capture_path": answers[0].get("mhtml_path") == answers[1].get("mhtml_path")}
        meta = {"url": "https://example.invalid/synthetic-article", "title": "Synthetic snapshot"}
        first = service._write_page(b"<html>FIRST SYNTHETIC VERSION</html>", meta)
        second = service._write_page(b"<html>SECOND SYNTHETIC VERSION</html>", meta)
        snapshots = {"same_path_after_refresh": first == second,
                     "first_path_now_has_second_bytes": b"SECOND SYNTHETIC" in first.read_bytes()}
        result = {"version": scholar_search.__version__, "same_runtime_lock": shared,
            "different_runtime_locks": separate, "same_doi_concurrent_miss": duplicate,
            "snapshot_mutability": snapshots, "real_browser_actions": 0}
    output = Path(os.environ["LOCALAPPDATA"]) / "scholar-search/verification/2026-11-26-codex-0.14.30"
    output.mkdir(parents=True, exist_ok=True)
    (output / "concurrency-checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
