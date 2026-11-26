"""One read-only bridge capture of the article already open in Edge.

No navigation, clicks, quota-state copies, or private patch installation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import scholar_search
from scholar_search.adapters.bridge import BridgeAdapter
from scholar_search.bootstrap import build_service
from scholar_search.core.contracts import Action
from scholar_search.core.errors import ScholarSearchError
from scholar_search.core.pageprobe import citation_doi, classify_mhtml


def main() -> None:
    endpoint = Path(os.environ["LOCALAPPDATA"]) / "scholar-search/host/bridge.json"
    service = build_service()
    service._adapter_factory = lambda: BridgeAdapter(endpoint=endpoint)
    result: dict[str, object] = {"client_version": scholar_search.__version__,
                                "navigation_actions": 0}
    try:
        saved = service.snapshot()
        result["snapshot"] = saved
        if saved.get("status") == "blocked":
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        path = Path(str(saved.get("path") or ""))
        if path.is_file():
            identifier = citation_doi(path)
            result["citation_doi"] = identifier
            result["classification"] = classify_mhtml(path, url=str(saved.get("url") or ""))
            if identifier.casefold() == "10.1021/acs.inorgchem.1c03019":
                result["conversion"] = service.page2md(mhtml_path=str(path))
                # Read-only capability check on the same publisher tab. No request to the site.
                adapter = BridgeAdapter(endpoint=endpoint)
                adapter.domains = ("pubs.acs.org",)
                try:
                    wait = adapter.execute(Action("wait_for", {
                        "selector": 'meta[name="citation_doi"]', "timeout_ms": 2000,
                    }), timeout_ms=4000)
                    result["publisher_wait"] = {"ok": wait.ok, "error": wait.error,
                                                "duration_ms": wait.duration_ms}
                finally:
                    adapter.close()
    except (ScholarSearchError, OSError, ValueError) as error:
        result["error"] = {"type": type(error).__name__, "message": str(error),
                           "code": getattr(error, "code", None)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
