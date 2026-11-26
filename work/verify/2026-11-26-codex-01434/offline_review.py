"""Installed 0.14.34 cross-layer checks and saved Springer output inspection; no network."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import scholar_search
from scholar_search import page2md
from scholar_search.adapters.bridge.policy import VERBS as HOST_VERBS, validate_request
from scholar_search.core.contracts import VERBS as CORE_VERBS
from scholar_search.core.params import validate_params
from scholar_search.core.policy import PolicyEngine
from scholar_search.core.risk import RiskGuard


def main() -> None:
    assert scholar_search.__version__ == "0.14.34"
    home = Path(os.environ["SCHOLAR_SEARCH_HOME"])
    evidence = home / "verification/2026-11-26-codex-0.14.34-p5"
    out = evidence / "conversions/springer-saved"
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    markdown = " ".join((out / "page.md").read_text(encoding="utf-8").split())
    sections = []
    for section in index["sections"]:
        path = out / section["file"]
        text = path.read_text(encoding="utf-8")
        blocks = [p for p in text.split("\n\n") if len(p.strip()) > 60]
        sections.append({"title": section["title"], "file_exists": path.is_file(),
                         "tokens": section["tokens"], "long_blocks": len(blocks),
                         "blocks_in_page_md": sum(" ".join(p.split()) in markdown for p in blocks)})
    expected_hash = "ec603b6b210bb7a20d2cd120a5f591e82f61dc84265fe0bffd115921cd0c7f70"
    actual_hash = hashlib.sha256((out / "page.mhtml").read_bytes()).hexdigest()
    assert actual_hash == meta["capture_sha256"] == expected_hash
    assert "Fabrication Steps and Error Possibility of Proposed SPR Sensor" in markdown
    assert "Conclusion" in markdown
    assert all(s["long_blocks"] == s["blocks_in_page_md"] for s in sections)
    assert sum(s["tokens"] for s in sections) == index["total_tokens"] == meta["tokens_total"]
    sample = "The mode is excited by light.\n\n## Conclusion\n\nImportant result."
    retained = page2md._cut_tail_markers(sample)
    tail_sample = "## Conclusion\n\nImportant result.\n\n## Cited By\n\nUnrelated material."
    cut = page2md._cut_tail_markers(tail_sample)
    params = {"halt_titles": ["请稍候", "just a moment"], "halt_url_markers": [],
              "timeout_ms": 10000, "poll_ms": 2000}
    gate = {"verb": "await_gate_clear", "core_verb_allowed": "await_gate_clear" in CORE_VERBS,
            "parameter_validation": validate_params("await_gate_clear", params),
            "host_verb_allowed": "await_gate_clear" in HOST_VERBS,
            "host_request_validation": validate_request({"action": "await_gate_clear", "params": params},
                                                       domains=("onlinelibrary.wiley.com",))}
    source = Path(__file__).resolve().parents[3] / "src/scholar_search"
    installed = Path(scholar_search.__file__).parent
    files = list(source.rglob("*.py"))
    differences = [str(p.relative_to(source)) for p in files
        if p.relative_to(source).as_posix() != "core/page_nav.py"
        and p.read_text(encoding="utf-8") != (installed / p.relative_to(source)).read_text(encoding="utf-8")]
    worker_name = "background-0.14.34.js"
    repository = Path(__file__).resolve().parents[3]
    worker_matches = (repository / "extension" / worker_name).read_text(encoding="utf-8") == (
        home / "browser/extension" / worker_name).read_text(encoding="utf-8")
    archive = home / "installations/0.14.34/bundle/dsh-wensu-0.14.34-reviewed.tgz"
    result = {"version": scholar_search.__version__, "real_browser_actions": 0,
        "cross_layer_wait_validation": gate,
        "springer": {"capture_sha256": actual_hash, "input_changed": meta.get("input_changed"),
                     "engine": meta["engine"], "coverage": meta["coverage"],
                     "sections": sections, "index_total_tokens": index["total_tokens"],
                     "excited_by_retained": retained == sample,
                     "real_cited_by_heading_removed": "Unrelated material" not in cut,
                     "conclusion_before_tail_retained": "Important result" in cut,
                     "warnings": meta.get("warnings")},
        "installation": {"source_files": len(files), "differences_excluding_private_override": differences,
                         "worker_disk_matches_reviewed_source": worker_matches,
                         "dsh_bundle_source": "local pack of repository release 628a264, three reviewed files",
                         "bundle_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()},
        "quota_remaining": PolicyEngine().remaining_today,
        "cooldown_until": str(RiskGuard().cooldown_until()) if RiskGuard().cooldown_until() else None}
    (evidence / "offline-review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
