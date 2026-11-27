"""离线复核 0.14.54 的三项修复（F53-01/02/03），输入是那次真实验收保存的捕获。

不访问任何网站：只读 `page.mhtml`，重新转换，检查表格是否进了 Markdown、分节与索引是否一致、
`pdf_url` 是否指向文章自身、`citation_doi` 是否是请求的那个 DOI（`declared_doi` 的来源）。

用法：
    python work/verify/2026-11-27-real-capture-0.14.54/check.py [捕获路径] [输出目录]
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

DEFAULT_CAPTURE = Path(
    r"C:\Users\xuhui\AppData\Local\scholar-search\verification\2026-11-27"
    r"\real-0.14.53-1a70620c\pages\10.3390_s26041303\page.mhtml"
)
EXPECTED_DOI = "10.3390/s26041303"
# 表头是短的事实性标签，不是正文；用它们判断"表真的进来了"，而不是判断措辞。
HEADERS = (
    "Sample Composition",
    "Manufacturing Technique",
    "Tensile Strength",
    "Mean Absolute Angle Error",
)


def main(argv: list[str]) -> int:
    capture = Path(argv[1]) if len(argv) > 1 else DEFAULT_CAPTURE
    if not capture.is_file():
        print(f"missing capture: {capture}")
        return 2
    out = Path(argv[2]) if len(argv) > 2 else Path(tempfile.mkdtemp(prefix="p2md-check-"))
    shutil.rmtree(out, ignore_errors=True)

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
    from scholar_search import page2md
    from scholar_search.core.pageprobe import citation_doi, classify_mhtml

    report: dict[str, object] = {"capture": str(capture), "out": str(out)}

    page2md.convert(capture, out)
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    page = (out / "page.md").read_text(encoding="utf-8")
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))

    report["tables_rendered"] = meta.get("tables_rendered")
    report["table_rows"] = meta.get("table_rows")
    report["tables_layout"] = meta.get("tables_layout")
    report["tables_unplaced"] = meta.get("tables_unplaced", 0)
    report["headers_present"] = {header: header in page for header in HEADERS}
    report["sections"] = meta.get("sections")
    report["tokens_total"] = meta.get("tokens_total")

    section_files = sorted((out / "sections").glob("*.md")) if (out / "sections").is_dir() else []
    entries = index.get("sections") or []
    report["section_files"] = len(section_files)
    report["index_sections"] = len(entries)
    # Compare like with like: `tokens` in the index is the estimator, `_word_count` is prose words.
    report["index_sum_tokens"] = sum(int(entry.get("tokens") or 0) for entry in entries)
    report["index_total_tokens"] = index.get("total_tokens")
    report["every_entry_has_a_file"] = all(
        (out / str(entry.get("file") or "")).is_file() for entry in entries
    )

    probe = classify_mhtml(capture)
    report["pdf_url"] = probe.get("pdf_url")
    report["citation_doi"] = citation_doi(capture)
    report["doi_matches"] = report["citation_doi"] == EXPECTED_DOI

    print(json.dumps(report, ensure_ascii=False, indent=2))

    ok = (
        isinstance(report["tables_rendered"], int)
        and report["tables_rendered"] >= 3
        and isinstance(report["table_rows"], int)
        and report["table_rows"] >= 22
        and all(report["headers_present"].values())  # type: ignore[union-attr]
        and report["doi_matches"] is True
        and str(report["pdf_url"]).endswith("/pdf")
        and "flyer" not in str(report["pdf_url"])
        and report["index_sum_tokens"] == report["index_total_tokens"]
        and report["index_sections"] == report["section_files"]
        and report["every_entry_has_a_file"] is True
    )
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
