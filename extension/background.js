/* scholar-search bridge — service worker.
 *
 * Relays actions from the native host to one bound tab. The extension only
 * accepts hosts inside its configured scope (the selected channel); the kernel
 * and native host enforce the same list independently.
 */

const HOST_NAME = "com.scholar.search";
const PROTOCOL_VERSION = 1;
const DEFAULT_DOMAINS = [  "kns.cnki.net",
  "www.cnki.net",
  "webofscience.clarivate.cn",
  // The apex covers `www.` and any other subdomain through the same
  // `host === d || host.endsWith("." + d)` test the kernel uses.
  "webofscience.com",
];

// Bounded by the action's own deadline: waiting longer than the caller will is waiting for
// nobody. The floor covers a download that has not started yet — the site renders the
// export server-side before the browser sees a file at all.
//
// The ceiling is `declared - 3000` rather than `declared`: the host gives the whole action
// 15 s and the click itself takes ~2 s, so a wait that used the full budget would always
// lose to the host's deadline and report `bridge.timeout` for a download that may well have
// landed.
function downloadBudget(params) {
  const declared = Number(params && params.timeout_ms);
  const base = Number.isFinite(declared) && declared > 0 ? declared : 8_000;
  return Math.min(Math.max(base - 3_000, 3_000), 14_000);
}

function isBibtexDownload(item) {
  if (!item) return false;
  const url = String(item.url || "");
  if (/\bbibtex\b/i.test(url)) return true;
  const name = String(item.filename || "").split(/[\\/]/).pop() || "";
  // Web of Science names every export `savedrecs.bib`, then `savedrecs (1).bib`, and so on.
  return /^savedrecs( \(\d+\))?\.bib$/i.test(name) || /\.bib$/i.test(name);
}

// The tab that started the download, so a file the user is downloading by hand cannot be
// mistaken for ours. Falls back to the shape check when the browser reports no tab.
//
// **Polled, not event-driven.** `chrome.downloads.onCreated` is the obvious mechanism and
// it did not work here: on a run that produced a complete 170 KB export the listener fired
// zero times (and once fired for the right download but with the empty `filename` a `blob:`
// URL starts with). Polling the download list costs a few API calls per second, needs no
// listener, and cannot be missed by a service worker that was suspended in between.
//
// Resolves `{ found, seen }`. `seen` records recent downloads that were rejected and why —
// without it a failed match is indistinguishable from no download at all.
function waitForDownload(tabId, deadline, startedAfter) {
  return new Promise((resolve) => {
    let settled = false;
    const seen = [];

    const note = (item, why) => {
      if (seen.length >= 3) return;
      seen.push({
        why,
        filename: String((item && item.filename) || "").split(/[\\/]/).pop() || "",
        url: String((item && item.url) || "").slice(0, 90),
        tab: item && Number.isInteger(item.tabId) ? item.tabId : null,
        state: (item && item.state) || "",
      });
    };

    const finish = (payload) => {
      if (settled) return;
      settled = true;
      resolve({ found: payload, seen });
    };

    const tick = () => {
      if (settled) return;
      chrome.downloads.search({ orderBy: ["-startTime"], limit: 10 }, (items) => {
        if (settled) return;
        for (const item of items || []) {
          const started = Date.parse(item.startTime || "") || 0;
          if (started && started < startedAfter - 2_000) continue;
          const name = String(item.filename || "");
          const owned = Number.isInteger(item.tabId) && item.tabId >= 0 && Number.isInteger(tabId)
            ? item.tabId === tabId
            : null;
          const bib = /\.bib$/i.test(name) || /\bbibtex\b/i.test(String(item.url || ""));
          if (owned === false && !bib) {
            note(item, "other-tab");
            continue;
          }
          if (item.state === "interrupted") {
            note(item, "interrupted");
            continue;
          }
          if (item.state !== "complete") continue;
          if (!name) {
            note(item, "no-filename");
            continue;
          }
          return finish({
            path: name,
            filename: name.split(/[\\/]/).pop() || "",
            size: item.fileSize || item.totalBytes || 0,
          });
        }
        if (Date.now() < deadline) setTimeout(tick, 300);
        else finish(null);
      });
    };

    tick();
  });
}

let port = null;let boundTabId = null;
let reconnectDelayMs = 3000;

function connect() {
  if (port) return;
  try {
    const channel = chrome.runtime.connectNative(HOST_NAME);
    port = channel;
    reconnectDelayMs = 3000;
    channel.onMessage.addListener((message) => onHostMessage(message, channel));
    channel.onDisconnect.addListener(() => {
      if (port === channel) port = null;
      // A host that was never registered fails differently from one that exited.
      // Retrying every 3 s regardless spawned another launcher process each time,
      // so a missing registration turned into a loop of doomed processes.
      const error = chrome.runtime.lastError;
      const text = String((error && error.message) || "");
      if (/not found|not registered|forbidden|access/i.test(text)) {
        reconnectDelayMs = Math.min(reconnectDelayMs * 2, 60_000);
      }
      setTimeout(connect, reconnectDelayMs);
    });
  } catch (error) {
    port = null;
    reconnectDelayMs = Math.min(reconnectDelayMs * 2, 60_000);
    setTimeout(connect, reconnectDelayMs);
  }
}

function allowedHost(hostname, domains) {
  const host = String(hostname || "").toLowerCase();
  return domains.some((domain) => {
    const value = String(domain).toLowerCase();
    return host === value || host.endsWith(`.${value}`);
  });
}

function domainsFor(message) {
  const supplied = message && Array.isArray(message.domains) ? message.domains : [];
  return supplied.length ? supplied : DEFAULT_DOMAINS;
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tab;
}

function waitComplete(tabId, timeoutMs = 5000) {
  // Resolves either way. Waiting for "complete" is an optimistic assumption: a
  // heavy page may keep loading past the deadline, and a goto that fails there
  // used to throw, poisoning the whole bridge connection. The subsequent
  // wait_for is what actually decides whether the page is usable.
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve) => {
    const tick = async () => {
      try {
        const tab = await chrome.tabs.get(tabId);
        if (tab.status === "complete") return resolve();
      } catch (error) {
        return resolve();
      }
      if (Date.now() > deadline) return resolve();
      setTimeout(tick, 250);
    };
    tick();
  });
}

async function pageMeta(tabId) {
  // sendMessage never settles while the frame is being replaced, and a goto that
  // waits on it hangs forever. Race it against a deadline: the meta is only ever
  // a bonus (status/title), never required for the action to succeed.
  try {
    const result = await Promise.race([
      chrome.tabs.sendMessage(tabId, { type: "meta" }),
      new Promise((resolve) => setTimeout(() => resolve(null), 1000)),
    ]);
    return (result && result.data) || {};
  } catch (error) {
    return {};
  }
}

async function onHostMessage(message, channel) {
  if (!message) return;

  if (message.type === "hello") {
    channel.postMessage({
      type: "hello_ack",
      id: message.id,
      protocol: PROTOCOL_VERSION,
    });
    return;
  }
  if (message.type !== "action") return;

  const { id, action, params } = message;
  const domains = domainsFor(message);
  const reply = (payload) => channel.postMessage({ type: "action_result", id, ...payload });

  try {
    if (action === "goto") {
      const tab = await activeTab();
      if (!tab || !tab.id) throw new Error("no_active_tab");
      if (params.reload === true) {
        // A real reload, not a navigation to the same URL: a person pressing F5
        // gives the page `performance.navigation.type === "reload"`, and nagivating
        // would give "navigate" instead — a difference a page can read.
        // The kernel cannot check a URL it was not given, so the live one is
        // checked here, against the same allowlist.
        const current = await chrome.tabs.get(tab.id);
        if (!current.url) throw new Error("no_active_tab");
        const live = new URL(current.url);
        if (live.protocol !== "https:" || !allowedHost(live.hostname, domains)) {
          throw new Error("policy.domain");
        }
        // bypassCache matters: a plain reload() restores the page from cache and
        // issues no network request at all, so the capture never sees a stream.
        // With it, the refresh re-fetches everything — and still reports
        // navigation type "reload", which is what a person pressing F5 produces.
        await chrome.tabs.reload(tab.id, { bypassCache: true });
      } else {
        const url = new URL(params.url);
        if (url.protocol !== "https:" || !allowedHost(url.hostname, domains)) {
          throw new Error("policy.domain");
        }
        await chrome.tabs.update(tab.id, { url: params.url });
      }
      await waitComplete(tab.id);
      await new Promise((resolve) => setTimeout(resolve, 500 + Math.random() * 1000));

      const updated = await chrome.tabs.get(tab.id);
      const finalUrl = updated.url || params.url;
      const meta = await pageMeta(updated.id);
      const status = Number(meta.status || 0);
      const outOfScope = !allowedHost(new URL(finalUrl).hostname, domains);
      const data = {
        ...meta,
        url: finalUrl,
        title: updated.title || "",
        status: status || undefined,
      };
      if (outOfScope || status >= 400) {
        // Refuse the navigation, but keep the final URL so the kernel can see
        // a login/verify redirect and persist the cooldown.
        return reply({
          ok: false,
          error: outOfScope ? "policy.domain" : `HTTP ${status}`,
          data,
        });
      }
      boundTabId = updated.id;
      return reply({ ok: true, data });
    }

    const tabId = boundTabId !== null ? boundTabId : (await activeTab())?.id;
    if (!tabId) throw new Error("no_active_tab");
    // Checked whether or not the tab has been bound yet: before this, the first
    // action on an unbound tab ran against whatever page happened to be active.
    const current = await chrome.tabs.get(tabId).catch(() => null);
    if (!current || !current.url) throw new Error("policy.tab_scope");
    let currentHost = "";
    try {
      currentHost = new URL(current.url).hostname;
    } catch (error) {
      throw new Error("policy.tab_scope");
    }
    if (!allowedHost(currentHost, domains)) throw new Error("policy.tab_scope");

    const message = { type: "dom_action", action, params };

    // A pause does not touch the page, so it must not wait for one.
    //
    // `sleep` used to be forwarded to the content script like everything else, and the
    // plan opens with `goto` then a pause. Right after a navigation the content script
    // is re-injected at document_idle, so the pause sat in the retry loop below and
    // spent its entire budget waiting for a script that had nothing to do — the run
    // died with `sleep failed: bridge.timeout (step 2/7)` on a page that had loaded
    // perfectly well. Waiting here instead costs exactly `params.ms` and cannot be
    // blocked by a slow page.
    if (action === "sleep") {
      const ms = Math.max(0, Math.min(Number(params && params.ms) || 0, 3_000));
      const began = Date.now();
      await new Promise((resolve) => setTimeout(resolve, ms));
      return reply({ ok: true, data: {}, duration_ms: Date.now() - began, url: current.url });
    }

    // document_idle injection can lag behind a navigation. A fixed 6 x 300 ms gave
    // a slow page 1.8 s and then declared the extension broken; back off instead.
    //
    // The budget now comes from the action's own deadline rather than a fixed eight
    // attempts. Eight attempts reached ~6.4 s and gave up while the kernel was still
    // willing to wait 11 s, so a Web of Science summary page that had just been
    // reloaded failed as `content_not_ready` with 4.6 s of its budget unspent. Stopping
    // 600 ms early keeps the error specific: the host's deadline would otherwise fire
    // first and report `bridge.timeout`, which says less.
    const declaredBudget = Number(params && params.timeout_ms);
    const budget = Math.min(
      Math.max(Number.isFinite(declaredBudget) ? declaredBudget : 8_000, 2_000) - 600,
      12_000,
    );
    const deadline = Date.now() + Math.max(budget, 1_000);
    let lastError = "";

    const sendToTab = async () => {
      let delay = 200;
      while (Date.now() < deadline) {
        try {
          return await chrome.tabs.sendMessage(tabId, message);
        } catch (error) {
          const text = String((error && error.message) || error);
          lastError = text;
          // A navigation tears down the content script mid-flight. All three
          // wordings mean "the new document is not ready yet", not "the page is
          // broken", so they are retried rather than surfaced.
          if (!/Receiving end|Could not establish|message channel closed/i.test(text)) {
            throw error;
          }
          const remaining = deadline - Date.now();
          if (remaining <= 0) break;
          await new Promise((resolve) => setTimeout(resolve, Math.min(delay, remaining)));
          delay = Math.min(delay * 2, 1000);
        }
      }
      // Carry the tab's URL and the channel's own wording. A bare
      // `content_not_ready` cannot distinguish "no such tab", "the document is not
      // there yet" and "the script is there but its channel closed", and one
      // investigation was spent guessing between them.
      throw Object.assign(new Error("content_not_ready"), {
        detail: { url: current.url, reason: lastError.slice(0, 160), waited_ms: budget },
      });
    };

    // The download is created *while the click is being handled*, so the listener has to be
    // in place before the click is dispatched. Attaching it after the content script replied
    // missed every file: `onCreated` had already fired, the wait timed out, and a run that
    // produced a complete 170 KB export reported "no file". The listener therefore starts
    // here and is awaited where the reply is assembled.
    const pendingDownload =
      action === "click" && params && params.expect_download
        ? waitForDownload(tabId, Date.now() + downloadBudget(params), Date.now() - 1_500)
        : null;

    let result;
    if (action === "click") {
      // A navigational click can destroy the content-script context before it
      // replies, so a lost reply means "navigation started". Only that counts:
      // a missing element or a refusal must surface, or the caller sees success
      // for a click that never happened.
      //
      // This deadline is a **fallback against hanging**, not a decision. It used to
      // be a hard 2 s, which silently cut off every click the plan had given more
      // time to: the WoS submit asks for `wait_until: "enabled"` with a 10 s budget,
      // and that budget was being discarded here. The result was a click reported as
      // successful at 2.004 s while the site was still working, so the next step read
      // the URL too early and reloaded the search form.
      //
      // The plan's own `timeout_ms` now sets the ceiling (clamped, because an action
      // payload must not be able to hang a tab indefinitely). 2 s remains the floor
      // for callers that pass nothing.
      const declared = Number(params && params.timeout_ms);
      const budget = Number.isFinite(declared) && declared > 0
        ? Math.min(Math.max(declared, 2_000), 30_000)
        : 2_000;
      try {
        result = await Promise.race([
          sendToTab(),
          new Promise((resolve) => setTimeout(() => resolve(undefined), budget)),
        ]);
      } catch (error) {
        const text = String((error && error.message) || error);
        if (!/Receiving end|Could not establish|message channel closed|content_not_ready/i.test(text)) {
          throw error;
        }
        result = undefined;
      }
      if (result === undefined) {
        // No snapshot is available: the document was replaced mid-click. The risk
        // layer reads a missing `captcha_visible` as "no opinion", which is the
        // honest answer here, and the plan's next wait_for verifies the page.
        const data = { navigation_expected: true };
        if (pendingDownload) {
          const outcome = await pendingDownload;
          if (outcome.found) data.download = outcome.found;
          else if (outcome.seen.length) data.download_seen = outcome.seen;
        }
        return reply({ ok: true, data });
      }
    } else {
      result = await sendToTab();
    }
    if (!result) throw new Error("dom_failed");
    const data = { ...(result.data || {}) };
    // Report where the tab actually is, not whether a navigation *seemed* to start.
    // A click that matched nothing leaves the page on the search form; the URL is
    // the site's own statement about that.
    //
    // Only when the caller asked for it (`wait_until`). Polling on every click added
    // a fixed six-second wait that pushed ordinary submits past their deadline —
    // CNKI surfaced it as `click failed: bridge.timeout` on a click that had worked.
    if (action === "click" && params.wait_until) {
      const before = (await chrome.tabs.get(tabId).catch(() => null))?.url || "";
      const deadline = Date.now() + 6000;
      let after = before;
      while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 250));
        after = (await chrome.tabs.get(tabId).catch(() => null))?.url || after;
        if (after !== before) break;
      }
      if (after) data.url = after;
      data.url_changed = Boolean(after) && after !== before;
    } else if (action === "click") {
      const after = await chrome.tabs.get(tabId).catch(() => null);
      if (after && after.url) data.url = after.url;
    } else {
      const after = await chrome.tabs.get(tabId).catch(() => null);
      if (after && after.url) data.url = after.url;
    }
    // A click that asks for it can be followed by a file download, and the file itself is
    // the payload we want. Reporting the path here is why no tenth verb was needed: the
    // caller already had to click to make the export happen, so the click is the natural
    // place to say where the result went.
    if (pendingDownload) {
      const outcome = await pendingDownload;
      if (outcome.found) data.download = outcome.found;
      else if (outcome.seen.length) data.download_seen = outcome.seen;
    }
    return reply({ ok: Boolean(result.ok), error: result.error, data });
  } catch (error) {
    // `detail` carries facts the message cannot: the tab's URL, the channel's own
    // failure wording. The kernel turns a `url` into `[reached <host>]`, which is how
    // an auth redirect was told apart from a slow page.
    const detail = error && typeof error === "object" ? error.detail : undefined;
    return reply({
      ok: false,
      error: String((error && error.message) || error),
      data: detail && typeof detail === "object" ? { ...detail } : {},
    });
  }
}

chrome.runtime.onInstalled.addListener(connect);
chrome.runtime.onStartup.addListener(connect);
connect();




