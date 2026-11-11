"""CSS anchors for the Web of Science (Clarivate China mirror) 2026.11 layout.

Captured from the live advanced-search and result pages on 2026-11-08. WoS is an
Angular app that ships ``data-ta`` attributes for its own automation, so those
are preferred over generated Material class names.

Rule of thumb for this file: never anchor on an id that contains a counter
(``cdk-overlay-9``, ``mat-menu-panel-54``) or on ``_ngcontent-*`` hashes — they
change per render.
"""

from __future__ import annotations

# The global site, Core Collection. Both hosts run the same application behind the same
# API — a capture from `www.webofscience.com` shows
# `/api/wosnx/core/runQueryGetRecordsStream?SID=…` returning 102 KB, exactly what the
# mirror returns — so `parse_records` reads either one.
#
# This was `webofscience.clarivate.cn`, the China mirror. A mirror is not a convenience:
# it is a separate origin with its own cookies, and it only resolves for a session
# granted access there. Off an institutional IP the navigation is handed to
# `access.clarivate.com` and the run stops on a login redirect. The global site is the
# entry a personal login can reach, so it is the default; the mirror is still allowed by
# the manifest and works by pointing this constant at it.
#
# `woscc` is Core Collection and stays. `/wos/alldb/` is All Databases: its records come
# from BIOSIS, MEDLINE, Derwent and others, where `ut` is `MEDLINE:…` rather than `WOS:…`,
# and the detail URL, the `exclude_ut` list and the JCR lookup all assume a Core
# Collection identifier. That is a different product, not a different spelling.
ADVANCED_SEARCH = "https://www.webofscience.com/wos/woscc/advanced-search"

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

DETAIL_PREFIX = "https://www.webofscience.com/wos/woscc/full-record/"
