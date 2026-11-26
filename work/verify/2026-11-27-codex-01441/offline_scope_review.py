"""Installed-version state-scope checks. No adapter, site, or real policy-state mutations."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import scholar_search
from scholar_search import bootstrap
from scholar_search.core.config import adopt_legacy_state, browser_state_paths
from scholar_search.core.contracts import RiskSignal
from scholar_search.core.errors import RiskBlocked
from scholar_search.core.locking import interprocess_lock


@contextmanager
def isolated(home: Path, shared: Path) -> Iterator[None]:
    old = {name: os.environ.get(name) for name in ["SCHOLAR_SEARCH_HOME", "SCHOLAR_SEARCH_BROWSER_STATE"]}
    os.environ["SCHOLAR_SEARCH_HOME"] = str(home)
    os.environ["SCHOLAR_SEARCH_BROWSER_STATE"] = str(shared)
    try:
        yield
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def file_hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def main() -> None:
    assert scholar_search.__version__ == "0.14.41"
    real_paths = browser_state_paths()[:2]
    before = [file_hash(p) for p in real_paths]
    real_home = Path(os.environ["SCHOLAR_SEARCH_HOME"])
    evidence = real_home / "verification/2026-11-27-codex-0.14.41-p5"
    runtime = evidence / "synthetic" / uuid.uuid4().hex
    homes = [runtime / "home-a", runtime / "home-b"]
    shared = runtime / "browser-state"
    url = "https://www.mdpi.com/synthetic-article"
    doi = "10.3390/synthetic"
    meta = {"url": url, "title": "Synthetic article"}
    with isolated(homes[0], shared):
        first = bootstrap.build_service()
        stage_a = first._stage_page(b"<html>FIRST SYNTHETIC ARTICLE</html>", meta)
        published_a, sha_a = first._publish_page(stage_a, meta, doi)
        first._page_cache_put(url, {"status": "ok", "mhtml_path": str(published_a),
                                   "capture_sha256": sha_a, "title": "Synthetic A"})
        first._note_job({"job_id": "synthetic-job-a", "terminal": "ok", "stage": "publish"})
        reader_after_a = bootstrap._last_job()
        lock_a = first._browser_lock_path()
    with isolated(homes[1], shared):
        second = bootstrap.build_service()
        cache_from_a = second._page_cache_get(url)
        job_from_a = second.last_job()
        stage_b = second._stage_page(b"<html>SECOND SYNTHETIC ARTICLE</html>", meta)
        published_b, _ = second._publish_page(stage_b, meta, doi)
        second._note_job({"job_id": "synthetic-job-b", "terminal": "ok", "stage": "publish"})
        reader_after_b = bootstrap._last_job()
        lock_b = second._browser_lock_path()
    first._policy.wait_turn(channel="synthetic", verb="goto")
    second._policy.wait_turn(channel="synthetic", verb="goto")
    first._risk.trip(RiskSignal.HTTP_403, "synthetic refusal; not a site request")
    second_refused = False
    try:
        second._risk.ensure_ready()
    except RiskBlocked:
        second_refused = True
    scope = {"same_quota_path": first._policy.state_path == second._policy.state_path,
             "synthetic_used_seen_by_a": first._policy.used_today,
             "synthetic_used_seen_by_b": second._policy.used_today,
             "cooldown_seen_by_b": second_refused,
             "same_browser_lock": lock_a == lock_b,
             "same_page_cache_path": first._page_cache_path() == second._page_cache_path(),
             "home_b_serves_home_a_cache": bool(cache_from_a),
             "home_b_sees_home_a_job": (job_from_a or {}).get("job_id") == "synthetic-job-a",
             "same_capture_path": published_a == published_b,
             "home_a_path_now_has_home_b_bytes": b"SECOND SYNTHETIC" in published_a.read_bytes(),
             "capture_under_requested_home_a": published_a.is_relative_to(homes[0]),
             "capture_under_requested_home_b": published_b.is_relative_to(homes[1]),
             "capture_under_shared_browser_state": published_a.is_relative_to(shared),
             "service_writer_job_path": str(first._last_job_path()),
             "bootstrap_reader_a_job_path": str(homes[0] / "state/last-job.json"),
             "bootstrap_last_job_after_write_a": reader_after_a,
             "bootstrap_last_job_after_write_b": reader_after_b}

    barrier = threading.Barrier(2)
    guard = threading.Lock()
    state = {"active": 0, "maximum": 0}

    def lock_worker(path: Path) -> None:
        barrier.wait(5)
        with interprocess_lock(path, timeout_s=5):
            with guard:
                state["active"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
            time.sleep(0.08)
            with guard:
                state["active"] -= 1

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        list(pool.map(lock_worker, [lock_a, lock_b]))
    scope["maximum_inside_shared_lock"] = state["maximum"]

    # Deterministic legal startup interleaving: both callers observe absent target before
    # either writes. A proxy only schedules those filesystem operations; production code runs.
    race = runtime / "migration-race"
    race.mkdir(parents=True)
    sources = []
    for used in [77, 11]:
        p = race / f"legacy-{used}.json"
        p.write_text(json.dumps({"day": date.today().isoformat(), "used": used, "last": None}), encoding="utf-8")
        sources.append(p)
    target = race / "shared/quota.json"
    absence = threading.Barrier(2)
    high_written = threading.Event()

    class ScheduledTarget:
        def __init__(self, index: int) -> None:
            self.index = index

        @property
        def parent(self) -> Path:
            return target.parent

        def exists(self) -> bool:
            observed = target.exists()
            absence.wait(5)
            return observed

        def write_bytes(self, payload: bytes) -> int:
            if self.index == 1:
                assert high_written.wait(5)
            count = target.write_bytes(payload)
            if self.index == 0:
                high_written.set()
            return count

    def migrate(index: int) -> bool:
        return adopt_legacy_state(sources[index], ScheduledTarget(index))  # type: ignore[arg-type]

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        migrations = list(pool.map(migrate, range(2)))
    migrated = json.loads(target.read_text(encoding="utf-8"))
    race_result = {"scheduling": "both observed missing; used=77 wrote first, used=11 wrote second",
                   "both_reported_adoption": migrations, "first_written_used": 77,
                   "final_used": migrated["used"], "legacy_sources_retained": all(p.is_file() for p in sources)}
    sequential = adopt_legacy_state(sources[0], target)
    race_result["later_sequential_adoption_refused"] = not sequential

    normal = json.loads((evidence / "normal-mdpi-summary.json").read_text(encoding="utf-8"))
    real_writing_job = real_paths[0].with_name("last-job.json")
    job = json.loads(real_writing_job.read_text(encoding="utf-8")) if real_writing_job.is_file() else None
    result: dict[str, Any] = {"version": scholar_search.__version__, "real_browser_actions": 0,
        "scope": scope, "migration_race": race_result,
        "real_normal_publication_path": normal["response"].get("mhtml_path"),
        "real_status_last_job_after_success": normal["post_status"].get("last_job"),
        "real_shared_job_marker_present": bool(job),
        "real_policy_files_unchanged_by_offline_checks": before == [file_hash(p) for p in real_paths]}
    (evidence / "offline-scope-review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
