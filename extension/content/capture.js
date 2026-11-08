/* wensu bridge — WoS result-stream capture.
 *
 * Runs in the page's own world at document_start, so it can wrap the transport
 * before the application boots. It never builds a request of its own — it only
 * mirrors what the page already asked for.
 *
 * Two endpoints carry records, and they arrive in sequence, not together:
 *
 *   runQuerySearch            first screen, 20 records, sent by the Search button
 *   runQueryGetRecordsStream  later batches, sent lazily when the list is
 *                             scrolled — this is how a "50 per page" setting
 *                             actually gets its remaining 30 records
 *
 * So the node is cleared only when a *primary* query starts, and every later
 * batch is appended. An earlier version cleared on any request and silently kept
 * just the last batch of 20.
 *
 * Handshake with the channel plan:
 *   - `data-ready` is dropped when the primary query starts;
 *   - it is restored once nothing is pending and the payload is in the node.
 * A single wait would match the previous run's marker the instant the click
 * returned.
 *
 * Diagnostics that survive the page: `data-wensu-capture="loaded"` proves the
 * script ran in the page world, `data-wensu-hits` counts tracked responses, and
 * `data-wensu-seen` lists request paths (query strings stripped, so no session
 * id leaks).
 */

(() => {
  const QUERY_PREFIX = "/api/wosnx/core/runQuery";
  const PRIMARY = "/api/wosnx/core/runQuerySearch";
  const ID = "wensu-wos-capture";
  const MAX_CHARS = 8 * 1024 * 1024;
  const seen = [];

  try {
    document.documentElement.setAttribute("data-wensu-capture", "loaded");
  } catch (error) {
    /* the document element is not guaranteed at the very first tick */
  }

  function remember(url) {
    try {
      const path = String(url || "").split("?")[0];
      if (!path || seen.indexOf(path) !== -1 || seen.length >= 30) return;
      seen.push(path);
      document.documentElement.setAttribute("data-wensu-seen", seen.join(" "));
    } catch (error) {
      /* ignore */
    }
  }

  let node = null;
  let pending = 0;
  let hits = 0;

  function ensureNode() {
    if (node && node.isConnected) return node;
    const existing = document.getElementById(ID);
    if (existing) {
      node = existing;
      return node;
    }
    node = document.createElement("div");
    node.id = ID;
    // Rendered on purpose: `wait_for` matches on visibility, not presence.
    node.setAttribute(
      "style",
      "position:fixed;top:0;left:0;width:1px;height:1px;overflow:hidden;" +
        "opacity:0;pointer-events:none;white-space:pre;font-size:0;z-index:-1"
    );
    (document.body || document.documentElement).appendChild(node);
    return node;
  }

  function begin(url) {
    const text = String(url || "");
    const element = ensureNode();
    // Every batch invalidates "ready", primary or not: the payload is only whole
    // once nothing is still pending.
    element.removeAttribute("data-ready");
    if (text.indexOf(PRIMARY) !== -1) {
      // A primary query means a new result set: drop whatever the last one left.
      element.textContent = "";
    }
    pending += 1;
    hits += 1;
    try {
      document.documentElement.setAttribute("data-wensu-hits", String(hits));
    } catch (error) {
      /* ignore */
    }
    ensureNode();
  }

  function append(chunk) {
    if (!chunk) return;
    const element = ensureNode();
    if (element.textContent.length > MAX_CHARS) return;
    if (element.textContent && !element.textContent.endsWith("\n")) {
      element.textContent += "\n";
    }
    element.textContent += chunk;
  }

  function finish() {
    pending = Math.max(0, pending - 1);
    if (pending > 0) return;
    ensureNode().setAttribute("data-ready", "1");
  }

  function tracked(url) {
    return typeof url === "string" && url.indexOf(QUERY_PREFIX) !== -1;
  }

  async function drain(response) {
    const body = response.body;
    if (!body || typeof body.getReader !== "function") {
      append(await response.text());
      return;
    }
    const reader = body.getReader();
    const decoder = new TextDecoder();
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value) append(decoder.decode(value, { stream: true }));
      }
      append(decoder.decode());
    } finally {
      reader.releaseLock();
    }
  }

  // -- fetch ---------------------------------------------------------------
  const nativeFetch = window.fetch;
  if (typeof nativeFetch === "function") {
    window.fetch = function (input) {
      const url = typeof input === "string" ? input : input && input.url;
      remember(url);
      const promise = nativeFetch.apply(this, arguments);
      if (!tracked(url)) return promise;
      begin(url);
      return promise.then(
        (response) => {
          try {
            drain(response.clone()).catch(() => {}).then(finish);
          } catch (error) {
            finish();
          }
          return response;
        },
        (error) => {
          finish();
          throw error;
        }
      );
    };
  }

  // -- XMLHttpRequest ------------------------------------------------------
  // Angular's HttpClient uses XHR unless told otherwise, so both transports are
  // wrapped rather than betting on one.
  const NativeXHR = window.XMLHttpRequest;
  if (typeof NativeXHR === "function") {
    const nativeOpen = NativeXHR.prototype.open;
    const nativeSend = NativeXHR.prototype.send;
    NativeXHR.prototype.open = function (method, url) {
      const text = String(url || "");
      remember(text);
      this.__wensuUrl = text;
      this.__wensuTracked = tracked(text);
      return nativeOpen.apply(this, arguments);
    };
    NativeXHR.prototype.send = function () {
      if (this.__wensuTracked) {
        begin(this.__wensuUrl);
        this.addEventListener("loadend", () => {
          try {
            const type = this.responseType;
            if (type === "" || type === "text") append(this.responseText);
          } catch (error) {
            /* opaque response: nothing to copy */
          } finally {
            finish();
          }
        });
      }
      return nativeSend.apply(this, arguments);
    };
  }
})();
