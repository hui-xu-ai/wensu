"""Offline protocol checks using the actual live handshake and synthetic outcomes."""
from __future__ import annotations

import importlib.util
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import scholar_search
from scholar_search.core.contracts import Action, Plan
from scholar_search.core.errors import ActionError
from scholar_search.core.publishers import publisher_for_doi


def main() -> None:
    assert scholar_search.__version__ == "0.14.33"
    evidence = Path(os.environ["SCHOLAR_SEARCH_HOME"]) / "verification/2026-11-26-codex-0.14.33-p5"
    live = json.loads((evidence / "single-mdpi-publish-summary.json").read_text(encoding="utf-8"))
    build = live["bridge_build"]
    helper_file = Path(__file__).resolve().parents[1] / "2026-11-26-codex-01429/verify_installed.py"
    spec = importlib.util.spec_from_file_location("p5_fixtures", helper_file)
    assert spec and spec.loader
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    runtime = evidence / "synthetic" / uuid.uuid4().hex

    service = h.fixture_service(runtime / "missing-capability", [
        {"verb": "goto", "data": {"url": "https://onlinelibrary.wiley.com/", "title": "Home"}},
        {"verb": "goto", "data": {"url": h.URL, "title": "Just a moment...", "halted": True}},
    ])
    factory = service._adapter_factory
    executed: list[str] = []

    class InfoAdapter:
        def __init__(self) -> None:
            self.inner = factory()

        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)

        def info(self) -> dict[str, Any]:
            return build

        def execute(self, action: Any, *, timeout_ms: int) -> Any:
            executed.append(action.verb)
            return self.inner.execute(action, timeout_ms=timeout_ms)

    service._adapter_factory = InfoAdapter
    publisher = publisher_for_doi(h.DOI)
    assert publisher
    gate_code = None
    try:
        service._ensure_capabilities(InfoAdapter(), Plan(channel="page:wiley", purpose="detail",
            actions=(Action("await_gate_clear", {"timeout_ms": 10000}),)))
    except ActionError as error:
        gate_code = error.code
    started = time.perf_counter()
    answer = service.read_page(doi=h.DOI)
    elapsed = time.perf_counter() - started
    gate_result = {"runtime_worker": build["worker"], "runtime_handshake": build["handshake"],
                   "advertised_capabilities": build["capabilities"], "gate_rejection": gate_code,
                   "executed_verbs": executed, "elapsed_seconds": round(elapsed, 4),
                   **{k: answer.get(k) for k in ["terminal", "stage", "reason", "quota_charged", "mhtml_path"]}}

    warm = h.fixture_service(runtime / "warmup-403", [
        {"verb": "goto", "data": {"url": "https://www.sciencedirect.com/science/article/pii/synthetic", "status": 403}},
    ])
    original_factory = warm._adapter_factory
    warm_executed: list[str] = []

    def recording_factory() -> Any:
        adapter = original_factory()
        execute = adapter.execute

        def recording(action: Any, *, timeout_ms: int) -> Any:
            warm_executed.append(action.verb)
            return execute(action, timeout_ms=timeout_ms)

        adapter.execute = recording
        return adapter

    warm._adapter_factory = recording_factory
    warm_answer = warm.warm_up(["10.1016/j.sna.2024.116038", h.DOI])
    result = {"version": scholar_search.__version__, "real_browser_actions": 0,
              "gate_protocol": gate_result,
              "warmup_first_403": {"response": warm_answer, "executed_verbs": warm_executed,
                  "actual_synthetic_quota_used": warm._policy.used_today,
                  "cooldown_present": bool(warm._risk.cooldown_until())}}
    (evidence / "protocol-regressions.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
