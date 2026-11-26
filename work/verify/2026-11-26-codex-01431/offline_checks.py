"""Installed-version regressions, synthetic adapters only; never connects to a host."""
from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import scholar_search
from lxml import html as lxml_html
from scholar_search import page2md
from scholar_search.core.page_nav import article_navigation
from scholar_search.core.pageprobe import citation_doi, meta_content
from scholar_search.core.publishers import publisher_for_doi, publisher_for_host
from scholar_search.core.service import _PAGE_JUDGE_REV, _page_capture_belongs

VERSION = "0.14.31"


def load_helper(name: str, file: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, file)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    assert scholar_search.__version__ == VERSION
    scripts = Path(__file__).resolve().parents[1]
    h = load_helper("fixtures_029", scripts / "2026-11-26-codex-01429/verify_installed.py")
    previous = load_helper("locks_030", scripts / "2026-11-26-codex-01430/concurrency_check.py")
    home = Path(os.environ["SCHOLAR_SEARCH_HOME"])
    evidence = home / f"verification/2026-11-26-codex-{VERSION}"
    evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wensu-031-offline-") as directory:
        root = Path(directory)
        template = h.fixture_service(root / "template", [])
        publisher = publisher_for_doi(h.DOI)
        assert publisher
        actions = article_navigation(template, h.URL, publisher)
        navigation = [{"verb": a.verb, "data": {"url": a.params.get("url"), "title": "Article"}}
                      for a in actions]
        service = h.fixture_service(root / "duplicate", [*navigation, {"verb": "sleep"}, h.capture(h.ARTICLE)])
        adapter_factory = service._adapter_factory
        executed_verbs: list[str] = []
        record_lock = threading.Lock()

        def recorded_adapter() -> Any:
            adapter = adapter_factory()
            execute = adapter.execute

            def recording_execute(action: Any, *, timeout_ms: int) -> Any:
                with record_lock:
                    executed_verbs.append(action.verb)
                return execute(action, timeout_ms=timeout_ms)

            adapter.execute = recording_execute
            return adapter

        service._adapter_factory = recorded_adapter
        original_get = service._page_cache_get
        barrier = threading.Barrier(2)
        first_get = threading.local()

        def simultaneous_initial_miss(url: str) -> Any:
            value = original_get(url)
            # Only synchronise the initial pre-lock lookup. The second lookup MUST be free
            # to run under the lock, otherwise the harness itself would deadlock the fix.
            if not getattr(first_get, "seen", False):
                first_get.seen = True
                barrier.wait(5)
            return value

        service._page_cache_get = simultaneous_initial_miss
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(service.read_page, doi=h.DOI) for _ in range(2)]
            answers = [future.result(15) for future in futures]
        duplicate = {"statuses": [a.get("status") for a in answers],
                     "reported_costs": [a.get("quota_charged") for a in answers],
                     "cached_flags": [bool(a.get("cached")) for a in answers],
                     "synthetic_quota_used": service._policy.used_today,
                     "executed_goto_count": executed_verbs.count("goto"),
                     "one_navigation_plan_goto_count": sum(a.verb == "goto" for a in actions),
                     "same_capture_path": answers[0].get("mhtml_path") == answers[1].get("mhtml_path")}

        wrong_url = "https://onlinelibrary.wiley.com/doi/10.1002/another-paper"
        wrong = h.fixture_service(root / "wrong-article", [*navigation, {"verb": "sleep"},
                                                       h.capture(h.ARTICLE, url=wrong_url)])
        wrong_answer = wrong.read_page(doi=h.DOI)
        identity = {"requested_doi": h.DOI, "captured_url": wrong_answer.get("captured_url"),
                    "status": wrong_answer.get("status"), "full_text": wrong_answer.get("full_text"),
                    "helper_accepts_wrong_article": _page_capture_belongs(wrong_url, "", publisher, h.DOI)}
        pku = publisher_for_host("whxb.pku.edu.cn")
        assert pku
        identity["unrelated_edu_cn_accepted"] = _page_capture_belongs(
            "https://unrelated.edu.cn/article", "", pku, "10.3866/synthetic")

        meta = {"url": "https://example.invalid/synthetic-article", "title": "Synthetic snapshot"}
        first = template._write_page(b"<html>FIRST SYNTHETIC VERSION</html>", meta)
        second = template._write_page(b"<html>SECOND SYNTHETIC VERSION</html>", meta)
        mutable = {"same_path_after_refresh": first == second,
                   "first_path_now_has_second_bytes": b"SECOND SYNTHETIC" in first.read_bytes()}

        stale = h.fixture_service(root / "stale-cache", [])
        old_capture = root / "old.mhtml"
        old_capture.write_bytes(h.mhtml(h.ARTICLE))
        stale._page_cache_path().parent.mkdir(parents=True, exist_ok=True)
        stale_doi = "10.3866/synthetic"
        requested_cache_key = f"https://doi.org/{stale_doi}"
        stale._page_cache_path().write_text(json.dumps({requested_cache_key: {
            "judge": 1, "status": "ok", "at": time.time(), "mhtml_path": str(old_capture),
            "captured_url": "https://unrelated.edu.cn/article", "full_text": True}}), encoding="utf-8")
        stale_answer = stale.read_page(doi=stale_doi)
        cached_identity = {"current_judge_revision": _PAGE_JUDGE_REV,
                           "status": stale_answer.get("status"), "cached": stale_answer.get("cached"),
                           "quota_charged": stale_answer.get("quota_charged"),
                           "captured_url": stale_answer.get("captured_url")}

        # Isolated quota accounting when the first navigation in a multi-action plan stops.
        first_block = h.fixture_service(root / "first-block", [
            {"verb": "goto", "data": {"url": navigation[0]["data"]["url"], "status": 403}}])
        blocked_answer = first_block.read_page(doi=h.DOI)
        # Source is deliberately plain div prose, so no supported extraction path can keep it.
        low_source = root / "low-coverage.html"
        low_source.write_text('<html><body><div>' + ' '.join(f'word{i}' for i in range(1000))
                              + '</div><section><h2>Introduction</h2><p>A short paragraph only.</p></section></body></html>',
                              encoding="utf-8")
        low_meta = page2md.convert(low_source, root / "low-md")
        short_source = root / "short-low-coverage.html"
        short_source.write_text('<html><body><div>' + ' '.join(f'word{i}' for i in range(400))
                                + '</div><section><h2>Introduction</h2><p>A short paragraph only.</p></section></body></html>',
                                encoding="utf-8")
        short_meta = page2md.convert(short_source, root / "short-low-md")
        fallback_source = root / "fallback.html"
        paragraphs = ''.join('<p>' + ' '.join(f'group{j}term{k}' for k in range(40))
                             + '</p>' for j in range(20))
        fallback_source.write_text('<html><body><div class="articleBody"><h2>Results</h2>'
                                   + paragraphs + '</div><h2>Supporting Information</h2>'
                                   + '<p>Extra tables.</p></body></html>', encoding="utf-8")
        fallback_out = root / "fallback-md"
        fallback_meta = page2md.convert(fallback_source, fallback_out, mode="core")
        marker = "group7term19"
        section_files = list((fallback_out / "sections").glob("*.md"))
        fallback_consistency = {
            "engine": fallback_meta.get("engine"), "coverage": fallback_meta.get("coverage"),
            "tokens_total": fallback_meta.get("tokens_total"), "sections_total": fallback_meta.get("sections_total"),
            "page_has_body_marker": marker in (fallback_out / "page.md").read_text(encoding="utf-8"),
            "any_section_has_body_marker": any(marker in p.read_text(encoding="utf-8") for p in section_files),
            "brief_has_body_marker": marker in (fallback_out / "page.brief.md").read_text(encoding="utf-8"),
            "core_has_body_marker": marker in (fallback_out / "page.core.md").read_text(encoding="utf-8"),
        }
        result = {"version": VERSION, "real_browser_actions": 0,
                  "same_runtime_lock": previous.lock_trial(root / "locks", True),
                  "different_runtime_locks": previous.lock_trial(root / "other-locks", False),
                  "same_doi_concurrent_miss": duplicate, "article_identity": identity,
                  "snapshot_mutability": mutable, "cached_identity_not_revalidated": cached_identity,
                  "first_navigation_blocked": {"status": blocked_answer.get("status"),
                       "reported_charge": blocked_answer.get("quota_charged"),
                       "actual_synthetic_charge": first_block._policy.used_today},
                  "low_coverage_probe": {"coverage": low_meta.get("coverage"),
                       "warnings": low_meta.get("warnings")},
                  "short_low_coverage_probe": {"coverage": short_meta.get("coverage"),
                       "warnings": short_meta.get("warnings")},
                  "synthetic_fallback_consistency": fallback_consistency,
                  "meta_attribute_probe": meta_content(
                      '<head><meta data-name="citation_doi" name="citation_reference" content="10.9999/wrong">'
                      '<meta name="citation_doi" content="10.9999/right"></head>', "citation_doi")}

    # Saved pages are reused locally. No additional visit to ACS or MDPI is made.
    current = json.loads((evidence / "normal-events.json").read_text(encoding="utf-8"))
    page = next(e["response"] for e in current if e["tool"] == "page_read")
    conversion = next(e["response"] for e in current if e["tool"] == "page2md")
    mdpi_source = Path(page["mhtml_path"])
    mdpi_html, _ = page2md._read_html(mdpi_source)
    # Check actual attributes independently of the product's regex metadata parser.
    mdpi_doc = lxml_html.fromstring(mdpi_html)
    direct_dois = [str(e.get("content") or "") for e in mdpi_doc.xpath("/html/head/meta")
                   if (e.get("name") or "").strip().casefold() == "citation_doi"]
    mdpi_meta = json.loads((Path(conversion["page_md"]).parent / "meta.json").read_text(encoding="utf-8"))
    result["mdpi"] = {"status": page.get("status"), "declared_doi": citation_doi(mdpi_source),
                      "independent_head_doi_attributes": direct_dois,
                      "response_declared_doi": page.get("declared_doi"),
                      **{k: mdpi_meta.get(k) for k in ["engine", "coverage", "tokens_total", "sections_total", "warnings"]}}
    prior_events = json.loads((home / "verification/2026-11-26-codex-0.14.30/natural-events.json").read_text(encoding="utf-8"))
    acs_page = next(e["response"] for e in prior_events if e["tool"] == "page_read")
    acs_source = Path(acs_page["mhtml_path"])
    out = evidence / "conversions/acs"
    acs_meta = page2md.convert(acs_source, out)
    acs_index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    result["acs_saved_capture"] = {**{k: acs_meta.get(k) for k in ["engine", "coverage", "bytes_md", "tokens_total", "sections_total", "warnings"]},
                                   "index": acs_index, "page_md": str(out / "page.md")}
    (evidence / "offline-checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
