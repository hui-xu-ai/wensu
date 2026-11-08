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
 *                             actually gets its remaining records
 *
 * So the node is cleared only when a *primary* query starts, and later batches
 * are appended. Three mistakes are worth not repeating:
 *
 *   - clearing on any request kept only the last batch of a multi-batch page;
 *   - inserting a newline per *chunk* cut the streamed JSON lines in half;
 *   - anchoring the node to <html> gave it 0x0 layout, and `wait_for` matches on
 *     visibility, so the plan timed out even though the data was there.
 *
 * "Finished" cannot rely on the stream closing: the response body often stays
 * open after the last record, so `done` never arrives and `finish()` never runs.
 * A short idle timer therefore declares the payload complete once chunks stop.
 *
 * The node lives in <body> (visible layout) and is re-attached with its buffer
 * intact if a render detaches it.
 *
 * Diagnostics: `data-wensu-capture="loaded"`, `data-wensu-hits` (tracked
 * responses), `data-wensu-rebuilds`, `data-wensu-seen` (request paths, query
 * stripped so no session id leaks).
 */

(() => {
  const QUERY_PREFIX = "/api/wosnx/core/runQuery";
  const PRIMARY = "/api/wosnx/core/runQuerySearch";
  const ID = "wensu-wos-capture";
  const MAX_CHARS = 8 * 1024 * 1024;
  const IDLE_MS = 1_500;
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
  let rebuilds = 0;
  let needSeparator = false;
  let buffer = "";
  let idleTimer = null;

  function ensureNode() {
    if (node && node.isConnected) {
      // Rendered matters: a node parked outside <body> gets 0x0 layout and
      // `wait_for` never matches it.
      if (document.body && node.parentElement !== document.body) {
        document.body.appendChild(node);
      }
      return node;
    }
    const existing = document.getElementById(ID);
    if (existing && existing.isConnected) {
      node = existing;
      if (document.body && node.parentElement !== document.body) {
        document.body.appendChild(node);
      }
      return node;
    }
    rebuilds += 1;
    node = document.createElement("div");
    node.id = ID;
    node.setAttribute(
      "style",
      "position:fixed;top:0;left:0;width:1px;height:1px;overflow:hidden;" +
        "opacity:0;pointer-events:none;white-space:pre;font-size:0;z-index:-1"
    );
    (document.body || document.documentElement).appendChild(node);
    try {
      document.documentElement.setAttribute("data-wensu-rebuilds", String(rebuilds));
    } catch (error) {
      /* ignore */
    }
    if (buffer) node.textContent = buffer;
    return node;
  }

  function markReady() {
    pending = 0;
    if (idleTimer) {
      clearTimeout(idleTimer);
      idleTimer = null;
    }
    ensureNode().setAttribute("data-ready", "1");
  }

  function looksComplete() {
    const text = buffer.replace(/\s+$/, "");
    if (!text) return false;
    if (text.endsWith("\n")) return true;
    const tail = text.slice(text.lastIndexOf("\n") + 1);
    if (!tail.trim()) return true;
    try {
      JSON.parse(tail);
      return true;
    } catch (error) {
      return false;
    }
  }

  function armIdle() {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      idleTimer = null;
      if (pending <= 0) return;
      if (looksComplete()) {
        markReady();
        return;
      }
      // The stream paused mid-line. Give it one more window rather than
      // declaring a truncated payload complete: a half-written JSON line fails
      // far more confusingly downstream than a plain timeout.
      idleTimer = setTimeout(() => {
        idleTimer = null;
        if (pending > 0) markReady();
      }, IDLE_MS * 2);
    }, IDLE_MS);
  }

  function begin(url) {
    const text = String(url || "");
    const element = ensureNode();
    element.removeAttribute("data-ready");
    if (text.indexOf(PRIMARY) !== -1) {
      // A primary query means a new result set: drop whatever the last one left.
      buffer = "";
      element.textContent = "";
      needSeparator = false;
    }
    needSeparator = true;
    pending += 1;
    hits += 1;
    try {
      document.documentElement.setAttribute("data-wensu-hits", String(hits));
    } catch (error) {
      /* ignore */
    }
  }

  function append(chunk) {
    if (!chunk) return;
    const element = ensureNode();
    if (buffer.length > MAX_CHARS) return;
    // One separator per *response*, never per chunk: NDJSON lines are split
    // across chunks arbitrarily, and a newline in the middle breaks them.
    if (needSeparator) {
      if (buffer) buffer += "\n";
      needSeparator = false;
    }
    buffer += chunk;
    element.textContent = buffer;
    armIdle();
  }

  function finish() {
    if (pending === 0) return;
    pending = Math.max(0, pending - 1);
    if (pending === 0) markReady();
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
