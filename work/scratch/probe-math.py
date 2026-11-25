"""How much math survives each saved capture, and does the raised cap change anything?

PowerShell swallows `$$` (it is a variable), so this runs from a file. Reads only local MHTMLs.

  - `<math` / `mjx-assistive-mml`: does the capture hold MathML at all (what pandoc can convert)?
  - `$$ … $$` blocks and inline `$…$` in the produced Markdown: what actually reached the page.
  - `math_truncated` / `math_failed` from the converter's counters.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

HOME = Path(os.environ["SCHOLAR_SEARCH_HOME"]).resolve()


def main() -> int:
    from scholar_search.bootstrap import build_service

    service = build_service()
    for page in sorted((HOME / "pages").glob("*/page.mhtml")):
        raw = page.read_text(encoding="utf-8", errors="replace")
        converted = service.page2md(mhtml_path=str(page))
        markdown = Path(str(converted["page_md"])).read_text(encoding="utf-8")
        blocks = len(re.findall(r"(?m)^\$\$.+?\$\$", markdown, re.S))
        inline = len(re.findall(r"(?<!\$)\$[^$\n]{1,400}\$(?!\$)", markdown))
        meta_path = Path(str(converted["page_md"])).parent / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        print(
            json.dumps(
                {
                    "page": page.parent.name[:36],
                    "mathml": raw.count("<math"),
                    "assistive": raw.count("mjx-assistive-mml"),
                    "mjx_lazy": raw.count("mjx-lazy"),
                    "math_blocks": blocks,
                    "math_inline": inline,
                    "math_engine": converted.get("math_engine"),
                    "truncated": meta.get("math_truncated"),
                    "failed": meta.get("math_failed"),
                    "warnings": converted.get("warnings"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
