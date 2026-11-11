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
 *                             scrolled — this is how a "50 per page" setting, or
 *                             a page turn, actually gets its remaining records
 *
 * The node is cleared only when a *primary* query starts, and later batches are
 * appended. Four mistakes are worth not repeating:
 *
 *   - clearing on any request kept only the last batch of a multi-batch page;
 *   - inserting a newline per *chunk* cut the streamed JSON lines in half;
 *   - anchoring the node to <html> gave it 0x0 layout, and `wait_for` matches on
 *     visibility, so the plan timed out even though the data was there;
 *   - a batch already in flight when a new page started appended its 20 records
 *     to the *new* page. Hence `generation`: every primary query bumps it, and a
 *     chunk or a completion from an older generation is dropped.
 *
 * "Finished" cannot rely on the stream closing: the response body often stays
 * open after the last record. A short idle timer declares the payload complete
 * once chunks stop — but only if the tail actually parses, otherwise a truncated
 * line would be handed downstream.
 *
 * Diagnostics: `data-wensu-capture="loaded"`, `data-wensu-hits` (tracked
 * responses), `data-wensu-rebuilds`, `data-wensu-seen` (request paths, query
 * stripped so no session id leaks).
 */

(() => {
  // Both hosts answer on the same API — the global site is the same application, not a
  // different one. A user's capture from `www.webofscience.com` shows
  // `/api/wosnx/core/runQueryGetRecordsStream?SID=…` returning 102 KB, so one prefix
  // covers both.
  //
  // `/api/esti/SearchEngine/…` was briefly added here and is deliberately absent. It is
  // the author-name typeahead, which fires while the expression is being typed; marking
  // it as a new result set made it clear the buffer *after* the real stream had arrived,
  // so the capture kept six author records and discarded the documents. That wreckage
  // was then read as "the global site uses a different format" — a wrong conclusion
  // built on a bug I had just introduced.
  const QUERY_PREFIX = "/api/wosnx/core/runQuery";
  const PRIMARY = "/api/wosnx/core/runQuerySearch";
  const ID = "wensu-wos-capture";
  const MAX_CHARS = 8 * 1024 * 1024;
  const IDLE_MS = 2_000;
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
  let generation = 0;
  let needSeparator = false;
  let buffer = "";
  let idleTimer = null;

  function ensureNode() {
    if (node && node.isConnected) {
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

  // `markReady` says "the payload is complete", but it was being called whenever the
  // buffer merely *parsed* — including when the buffer held only the `searchInfo`
  // block and no records at all. A plan waiting on `data-ready` then read an empty
  // capture and reported "the stream was not intercepted", which is a different
  // problem with a different fix.
  //
  // The site states how many records it will send, in the same `searchInfo` block, so
  // the honest test is "did the records I was promised arrive". A page that genuinely
  // matched nothing declares 0 and is ready immediately — that is a real answer, not
  // a wait.
  function declaredRecords() {
    const match = /"RecordsFound"\s*:\s*(\d+)/.exec(buffer);
    return match ? Number(match[1]) : null;
  }

  function carriesRecords() {
    // Tolerant of spacing and of the key appearing inside a larger object: the
    // payload is newline-delimited JSON written by the site, not by us, and an exact
    // pattern here would be a promise we cannot keep about someone else's format.
    return /"key"\s*:\s*"records"/.test(buffer) || /"records"\s*:/.test(buffer);
  }

  // How many idle windows to keep waiting for promised records before giving up and
  // letting the reader decide.
  //
  // This is the difference between "wait until the data is here" and "wait until my
  // test passes". The first version of `satisfiesDeclaredCount` had no bound: if the
  // site declared 115 records and this file's pattern did not recognise them, the
  // capture never became ready and the caller saw a 10 s timeout on a query that had
  // actually succeeded — the window title even said "115 results". A test that can
  // only ever be satisfied by one specific payload shape is not a readiness signal,
  // it is a trap.
  //
  // Three windows (~6 s) is longer than the observed inter-batch gap and far shorter
  // than the plan's capture deadline, so a real shortfall still reads as a short
  // capture downstream instead of a timeout here.
  const MAX_READY_WAITS = 3;
  let readyWaits = 0;

  function satisfiesDeclaredCount() {
    const declared = declaredRecords();
    if (declared === null) return true; // nothing promised: nothing to wait for
    if (declared === 0) return true; // the site itself says there are none
    if (carriesRecords()) return true;
    readyWaits += 1;
    return readyWaits > MAX_READY_WAITS;
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

  function armIdle(gen) {
    // One lazy batch is ~100 KB arriving over several chunks, and the gaps can
    // exceed a single idle window, so keep waiting while the tail is unparseable.
    // There is deliberately no attempt cap: giving up would hand a truncated JSON
    // line downstream, which reads as "the page had fewer records" — worse than a
    // timeout the plan can report. The plan's own wait deadline is the real bound.
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      idleTimer = null;
      if (gen !== generation) return;
      const element = ensureNode();
      if (element.getAttribute("data-overflow") === "1") {
        // Over the size cap: never declared ready, so the caller times out instead
        // of receiving a record set that silently stops mid-page.
        return;
      }
      if (!looksComplete()) {
        armIdle(gen);
        return;
      }
      // Records are promised but have not arrived yet: keep waiting rather than
      // declaring a payload that cannot answer the query.
      if (!satisfiesDeclaredCount()) {
        armIdle(gen);
        return;
      }
      markReady();
    }, IDLE_MS);
  }

  function begin(url) {
    const text = String(url || "");
    if (text.indexOf(PRIMARY) !== -1) {
      // A primary query means a new result set: drop everything the previous one
      // left behind, and invalidate every request still in flight.
      generation += 1;
      buffer = "";
      needSeparator = false;
      pending = 0;
      // A new result set gets a fresh readiness budget. Carrying the counter over
      // would let one slow capture cause the next one to give up immediately.
      readyWaits = 0;
      const element = ensureNode();
      element.removeAttribute("data-ready");
      element.textContent = "";
    }
    needSeparator = true;
    pending += 1;
    hits += 1;
    try {
      document.documentElement.setAttribute("data-wensu-hits", String(hits));
    } catch (error) {
      /* ignore */
    }
    return generation;
  }

  function append(chunk, gen) {
    if (!chunk || gen !== generation) return;
    const element = ensureNode();
    if (buffer.length > MAX_CHARS) {
      // Refuse to grow without bound, and record why. The marker stops the idle
      // timer from ever declaring this payload complete, so an oversized capture
      // surfaces as a timeout rather than as a short page.
      element.setAttribute("data-overflow", "1");
      return;
    }
    if (needSeparator) {
      if (buffer) buffer += "\n";
      needSeparator = false;
    }
    buffer += chunk;
    element.textContent = buffer;
    armIdle(gen);
  }

  function finish(gen) {
    if (gen !== generation) return;
    if (pending === 0) return;
    pending = Math.max(0, pending - 1);
    // Reaching zero does not mean the page is done: the lazy loader sends three
    // batches in sequence, with quiet gaps between them. Declaring ready here cut
    // the payload in half — the reader saw "95 results" on screen and 20 records
    // in the node. The idle timer decides instead, after a quiet window.
    armIdle(gen);
  }

  function tracked(url) {
    return typeof url === "string" && url.indexOf(QUERY_PREFIX) !== -1;
  }

  async function drain(response, gen) {
    const body = response.body;
    if (!body || typeof body.getReader !== "function") {
      append(await response.text(), gen);
      return;
    }
    const reader = body.getReader();
    const decoder = new TextDecoder();
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value) append(decoder.decode(value, { stream: true }), gen);
      }
      append(decoder.decode(), gen);
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
      const gen = begin(url);
      return promise.then(
        (response) => {
          try {
            drain(response.clone(), gen).catch(() => {}).then(() => finish(gen));
          } catch (error) {
            finish(gen);
          }
          return response;
        },
        (error) => {
          finish(gen);
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
        const gen = begin(this.__wensuUrl);
        this.addEventListener("loadend", () => {
          try {
            const type = this.responseType;
            if (type === "" || type === "text") append(this.responseText, gen);
          } catch (error) {
            /* opaque response: nothing to copy */
          } finally {
            finish(gen);
          }
        });
      }
      return nativeSend.apply(this, arguments);
    };
  }
})();
