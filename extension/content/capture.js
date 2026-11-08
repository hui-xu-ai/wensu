/* wensu bridge — WoS result-stream capture.
 *
 * Runs in the page's own world at document_start, so it can wrap the transport
 * before the application boots.
 *
 * Why copy instead of re-request: the page already asked for the 50 records; a
 * second request would be a second network action with none of the UI signals a
 * human click leaves behind. This script therefore never builds a request of
 * its own — it only mirrors what the page received.
 *
 * Handshake with the channel plan (channels/webofscience/v2026_11/plan_search):
 *   - `data-ready` is dropped the moment a tracked request starts;
 *   - it is restored to "1" once the stream ends and the payload is in the node.
 * The plan waits for "ready disappears, then reappears". A single wait would
 * match the previous run's marker the instant the click returned.
 *
 * Diagnostics that survive the page: `data-wensu-capture="loaded"` proves the
 * script ran in the page world, and `data-wensu-seen` lists the request paths
 * the app actually used. Query strings are stripped, so no session id leaks.
 */

(() => {
  // Two endpoints carry records: `runQuerySearch` answers the Search button and
  // `runQueryGetRecordsStream` answers a re-query (sort / page turn). Both hold
  // the same 50 records, so the prefix is matched once instead of betting on
  // which one the UI happened to use.
  const STREAM = "/api/wosnx/core/runQuery";
  const ID = "wensu-wos-capture";
  const MAX_CHARS = 4 * 1024 * 1024;
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
    // Rendered on purpose: `wait_for` matches on visibility, not on presence.
    // One transparent pixel at the viewport origin is "visible" to that check,
    // costs no layout and cannot be seen.
    node.setAttribute(
      "style",
      "position:fixed;top:0;left:0;width:1px;height:1px;overflow:hidden;" +
        "opacity:0;pointer-events:none;white-space:pre;font-size:0;z-index:-1"
    );
    (document.body || document.documentElement).appendChild(node);
    return node;
  }

  function begin() {
    // Only the first request of a burst clears the node. One search can arrive
    // as several `runQuery` responses (a 50-row page showed up as batches), and
    // wiping on each of them would leave only the last batch behind.
    if (pending === 0) {
      const element = ensureNode();
      element.removeAttribute("data-ready");
      element.textContent = "";
    }
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
    if (element.textContent.length > MAX_CHARS) return;
    element.textContent += chunk;
  }

  function finish() {
    pending = Math.max(0, pending - 1);
    if (pending > 0) return;
    ensureNode().setAttribute("data-ready", "1");
  }

  function tracked(url) {
    return typeof url === "string" && url.indexOf(STREAM) !== -1;
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
      begin();
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
      remember(url);
      this.__wensuTracked = tracked(String(url || ""));
      return nativeOpen.apply(this, arguments);
    };
    NativeXHR.prototype.send = function () {
      if (this.__wensuTracked) {
        begin();
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
