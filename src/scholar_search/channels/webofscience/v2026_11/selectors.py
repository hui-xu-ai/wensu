"""CSS anchors for the Web of Science (Clarivate China mirror) 2026.11 layout.

Captured from the live advanced-search and result pages on 2026-11-08. WoS is an
Angular app that ships ``data-ta`` attributes for its own automation, so those
are preferred over generated Material class names.

Rule of thumb for this file: never anchor on an id that contains a counter
(``cdk-overlay-9``, ``mat-menu-panel-54``) or on ``_ngcontent-*`` hashes — they
change per render.
"""

from __future__ import annotations

# The China mirror, because it is the only host this channel can currently **parse**.
#
# The global site (`www.webofscience.com`) is reachable — the extension is authorised
# there, injects, and captures — but it answers on a different API and in a different
# payload shape:
#
#   mirror : /api/wosnx/core/runQuery…  -> newline-delimited JSON
#            {"key": "searchInfo", "payload": {"RecordsFound": 115}}
#            {"key": "records",    "payload": [...]}
#   global : /api/esti/SearchEngine/…   -> one JSON document
#            {"QueryResult": {"RecordsFound": 6}, "Data": {"Records": [...]}}
#
# `parse_records` reads the first shape. Pointing this constant at the global site today
# would move the failure from "cannot reach the site" to "cannot read the answer", and
# would break the host that works. See docs/reviews for the captured sample and what
# supporting the global site requires.
ADVANCED_SEARCH = "https://webofscience.clarivate.cn/wos/woscc/advanced-search"

# The editor keeps whatever the previous search left in it; ``type`` always
# clears before writing (extension/content/actions.js), so runs cannot leak
# into each other even without an explicit reset.
QUERY_INPUT = "textarea#advancedSearchInputArea"
SUBMIT = "button[data-ta='run-search']"

# Sort menu. Opening the menu is the only way to change order: the order is not
# expressible in a search expression, so this costs two clicks.
SORT_OPEN = "button[data-ta='selectSortOption']"
SORT = {
    "date": "#date-descending",
    "citation": "#times-cited-descending",
}

NEXT_PAGE = "button[data-ta='next-page-button']"
PAGE_BOX = "input#snNextPageTop"

# Present only once the result list has rendered. The plan waits for it before
# scrolling, because a scroll on an unrendered list triggers no lazy load.
RESULT_READY = NEXT_PAGE

# The capture node written by the MAIN-world content script
# (extension/content/capture.js). It is deliberately rendered — one transparent
# pixel anchored at the viewport origin — because ``wait_for`` matches on
# visibility, not on presence.
CAPTURE = "#wensu-wos-capture"
CAPTURE_READY = "#wensu-wos-capture[data-ready='1']"

# Path fragment of the streaming endpoint that carries the 50 records. The real
# URLs also carry a session id in the query string; it is never stored.
CAPTURE_STREAM = "/api/wosnx/core/runQueryGetRecordsStream"

DETAIL_PREFIX = "https://webofscience.clarivate.cn/wos/woscc/full-record/"
