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
  // 55 s, not 14: a 1000-record export file does not arrive inside the old ceiling, so the
  // wait gave up and the caller was told "no file" for a download that was still coming
  // (ADR 0024). Small exports still finish in a second or two — this is a ceiling, not a wait.
  return Math.min(Math.max(base - 3_000, 3_000), 55_000);
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

// `pageCapture` writes the page and every resource into one MHTML file. The blob goes
// to the download manager, not to the bridge: the bridge speaks line-delimited JSON
// with a 1 MB frame cap, and a saved article is routinely 1–5 MB (ADR 0018).
// Base64 for a blob inside a service worker: `FileReader` is available there, and it
// avoids shipping the bytes through the bridge (which is a one-line-JSON channel).
// `chrome.tabs.get` right after `tabs.update` can still report the *previous* URL: the
// navigation has been requested but not committed. Reading it too early made a plan look
// like it had been redirected out of scope (`policy.domain` while the tab was in fact on
// its way to the right host). Wait until the tab reports the new document.
function waitNavigated(tabId, fromUrl, domains, timeoutMs = 10_000) {
  return new Promise((resolve) => {
    const deadline = Date.now() + timeoutMs;
    const tick = async () => {
      let tab = null;
      try {
        tab = await chrome.tabs.get(tabId);
      } catch {
        return resolve(null);
      }
      const url = String((tab && tab.url) || "");
      let inScope = false;
      try {
        inScope = allowedHost(new URL(url).hostname, domains);
      } catch {
        inScope = false;
      }
      // Any allowed host counts, not one hostname: a DOI hop starts at doi.org and ends
      // on the publisher, so waiting for `doi.org` to appear would always time out.
      const moved = url && url !== fromUrl && inScope;
      const settled = tab && tab.status === "complete" && inScope;
      if (moved || settled) return resolve(tab);
      if (Date.now() >= deadline) return resolve(tab);
      setTimeout(tick, 150);
    };
    tick();
  });
}

// One capture, handed out in chunks.
//
// The download manager is not usable for this: Edge holds every `.mhtml` download behind
// its file-reputation prompt, which shows up as a `未确认 NNNN.crdownload` that never
// completes. A service worker also cannot mint a `blob:` URL (MV3). So the page bytes are
// cached here and read back by the kernel over the bridge, a chunk per round trip.
const CHUNK_BYTES = 192 * 1024;
const captures = new Map();

function bytesToBase64(bytes) {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 0x8000) {
    binary += String.fromCharCode.apply(null, bytes.subarray(index, index + 0x8000));
  }
  return btoa(binary);
}

function sliceChunk(capture, offset) {
  const start = Math.max(0, Math.min(offset, capture.bytes.length));
  const end = Math.min(start + CHUNK_BYTES, capture.bytes.length);
  const slice = capture.bytes.subarray(start, end);
  if (end >= capture.bytes.length) captures.delete(capture.token);
  return bytesToBase64(slice);
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
    // Get the work tab ready off the action path. Doing this inside the first `goto` added
    // window creation and a tab move on top of a 13 s publisher load, which pushed the
    // action past the kernel's 15 s budget: the page opened, and the caller was told
    // `bridge.timeout` (2026-11-24, reproduced twice on Wiley).
    void workTab([]).catch(() => null);
    // The profile's windows are the tool's: minimize them (once per browser session) so starting
    // the browser does not put anything in the user's way.
    void quietWindows().catch(() => null);
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

// One tab, reused for every navigation.
//
// The first design navigated *whatever tab was active*, which hijacked the page the user
// was reading (and could have been the editor's own UI). A dedicated work tab keeps the
// footprint at exactly one tab, never touches a page the caller did not ask for, and gives
// `page_read` a predictable target to snapshot afterwards.
const WORK_TAB_KEY = "wensuWorkTabId";
// Tabs opened for a single navigation (`goto` with `open: "new"`). They are blanked on the
// next `goto`, so the browser never accumulates tabs.
const DISPOSABLE_KEY = "wensuDisposableTabs";
// Every tab this extension created, newest last. The work-tab id lives in `storage.local`,
// but that id can still point at a tab the user closed — and older builds remembered the id
// in `storage.session`, which is emptied when the extension reloads. Without this list the
// fallback below created one more `about:blank` on every reload and never removed the old
// one, so a profile slowly filled with them (2026-11-24, reported as the browser slowing
// down). The list is what makes "at most one tab of ours" true even after the id is lost.
const OWNED_KEY = "wensuOwnedTabs";
// The window that holds the work tab, so the agent's page stays out of the user's tab strip.
const WINDOW_KEY = "wensuWorkWindowId";
// The browser this extension drives belongs to the tool, not to the user: its windows are kept
// minimized so a search never takes the screen. Timers are not slowed by that — measured
// 2026-11-25 with the work window hidden for 5m40s, `sleep(150)` answered in 155 ms, the same as
// unfocused (156 ms) — so the pacing rules in ADR 0023 are untouched.
const QUIET_KEY = "wensuQuietWindows";

function dwellFor(params) {
  const declared = Number(params && params.dwell_ms);
  if (Number.isFinite(declared) && declared >= 0) return Math.min(declared, 3_000);
  return 250 + Math.random() * 200;
}

async function rememberDisposable(tabId) {
  if (!Number.isInteger(tabId)) return;
  const stored = (await chrome.storage.local.get(DISPOSABLE_KEY))[DISPOSABLE_KEY];
  const ids = Array.isArray(stored) ? stored.filter((id) => Number.isInteger(id)) : [];
  if (!ids.includes(tabId)) ids.push(tabId);
  const known = (await chrome.storage.local.get(OWNED_KEY))[OWNED_KEY];
  const owned = Array.isArray(known) ? known.filter((id) => Number.isInteger(id)) : [];
  await chrome.storage.local.set({
    [DISPOSABLE_KEY]: ids.slice(-5),
    // A transient tab is still a tab of ours: it becomes the work tab when it is blanked,
    // so it belongs in the same list the fallback consults.
    [OWNED_KEY]: [...new Set([...owned, tabId])].slice(-8),
  });
}

async function closeDisposableTabs() {
  // Blank them, do not close them. A closed tab cannot be reused, and the caller's next
  // navigation then has nowhere controlled to land; a blank tab can carry it.
  const stored = (await chrome.storage.local.get(DISPOSABLE_KEY))[DISPOSABLE_KEY];
  const ids = Array.isArray(stored) ? stored.filter((id) => Number.isInteger(id)) : [];
  await chrome.storage.local.set({ [DISPOSABLE_KEY]: [] });
  const blanked = [];
  for (const id of ids) {
    // Only ids this extension created are ever in this list; a failure means the user
    // closed it himself, which is not worth failing a plan over.
    const done = await chrome.tabs
      .update(id, { url: "about:blank" })
      .then(() => true)
      .catch(() => false);
    if (done) blanked.push(id);
  }
  // The newest one becomes *the* work tab, so the article and every later search land in
  // the tab we already own instead of a fresh one.
  const newest = blanked[blanked.length - 1];
  if (Number.isInteger(newest)) await chrome.storage.local.set({ [WORK_TAB_KEY]: newest });
  return blanked;
}

async function workTab(domains) {
  const tab = await resolveWorkTab(domains);
  // Pin it: a pinned tab is compact, visually separate from the user's own pages, and the
  // browser asks before closing it. Only tabs in our own list ever reach here — the user's
  // tabs are refused by `resolveWorkTab` — so pinning cannot touch anyone else's page.
  if (tab && tab.id) await within(chrome.tabs.update(tab.id, { pinned: true }), 1_000);
  return tab;
}

// `undefined` (rather than a rejection) when a browser call neither answers nor fails: a
// promise that never settles must not hold a navigation hostage.
async function within(promise, ms) {
  return Promise.race([
    promise.catch(() => null),
    new Promise((resolve) => setTimeout(() => resolve(null), ms)),
  ]);
}

function alive(tab) {
  return tab && Number.isInteger(tab.id) ? tab : null;
}

async function rememberedTab() {
  // Persistent storage, not `storage.session`: the session area is emptied when the
  // extension is reloaded or the browser restarts, while the tab it named survives — the
  // exact mismatch that used to leave one orphan tab per reload.
  const stored = (await chrome.storage.local.get(WORK_TAB_KEY))[WORK_TAB_KEY];
  if (!Number.isInteger(stored)) return null;
  return alive(await chrome.tabs.get(stored).catch(() => null));
}

async function adoptOwnedTab() {
  const known = (await chrome.storage.local.get(OWNED_KEY))[OWNED_KEY];
  const owned = Array.isArray(known) ? known.filter((id) => Number.isInteger(id)) : [];
  const found = [];
  for (const id of owned) {
    const tab = alive(await chrome.tabs.get(id).catch(() => null));
    if (tab) found.push(tab);
  }
  if (!found.length) return null;
  // Reuse the newest surviving tab of ours and drop the spares: an id this build forgot is
  // not a reason to open a second tab. Only ids this extension created are ever in the
  // list, so nothing of the user's is touched.
  const newest = found[found.length - 1];
  for (const spare of found.slice(0, -1)) await chrome.tabs.remove(spare.id).catch(() => null);
  await chrome.storage.local.set({ [WORK_TAB_KEY]: newest.id });
  return newest;
}

async function createWorkTab() {
  // Never adopt a tab the user opened himself. The previous version picked any tab whose
  // host was in scope and remembered it as the work tab, so the next `goto` navigated the
  // page the user was reading — the opposite of what the comment above promises
  // (2026-11-22, reproduced with tests/js/tab_lifecycle_probe.js).
  //
  // The new tab starts blank on purpose: creating it at a hard-coded publisher address
  // sent a request to Elsevier even when the article was a Wiley DOI.
  const created = await chrome.tabs.create({ url: "about:blank", active: false });
  const known = (await chrome.storage.local.get(OWNED_KEY))[OWNED_KEY];
  const owned = Array.isArray(known) ? known.filter((id) => Number.isInteger(id)) : [];
  await chrome.storage.local.set({
    [OWNED_KEY]: [...owned, created.id].slice(-8),
    [WORK_TAB_KEY]: created.id,
  });
  return created;
}

// A window of our own, so the agent's page never takes a slot in the user's tab strip.
// `focused: false` keeps the caret where the user left it. Everything here is best effort
// and deadline-bounded: if this browser will not hand out a window, the work tab simply
// stays where it is and the navigation still happens (a hang here looks exactly like a
// dead bridge — 2026-11-24, `bridge.timeout` at `navigate.open`).
async function minimizeWindow(id) {
  if (!id) return null;
  return within(chrome.windows.update(id, { state: "minimized" }), 1_000).catch(() => null);
}

async function quietWindows() {
  // Once per browser session. `storage.session` is cleared when the browser closes, while the
  // service worker restarts on its own far more often — a marker there keeps a window the user
  // restored deliberately from being minimized again a moment later under them.
  const marked = (await chrome.storage.session.get(QUIET_KEY))[QUIET_KEY];
  if (marked) return;
  const opened = await chrome.windows.getAll({ windowTypes: ["normal"] }).catch(() => null);
  for (const win of Array.isArray(opened) ? opened : []) await minimizeWindow(win && win.id);
  await chrome.storage.session.set({ [QUIET_KEY]: Date.now() });
}

async function isolateWorkTab(tab) {
  if (!tab) return tab;
  const stored = (await chrome.storage.local.get(WINDOW_KEY))[WINDOW_KEY];
  let win = Number.isInteger(stored)
    ? await within(chrome.windows.get(stored), 1_000)
    : null;
  if (win && win.id) {
    if (tab.windowId !== win.id) {
      await within(chrome.tabs.move(tab.id, { windowId: win.id, index: -1 }), 2_000);
    }
    await minimizeWindow(win.id);
    return (await chrome.tabs.get(tab.id).catch(() => null)) || tab;
  }
  const opened = await within(
    chrome.windows.create({ url: "about:blank", focused: false, type: "normal" }),
    2_000,
  );
  if (!opened || !opened.id) return tab; // no window: keep the user's tab strip as it is
  // `windows.create` answers with the window only — no tab list — so the blank tab it
  // opened has to be looked up (reading `win.tabs[0]` threw and the host got no reply).
  const blanked = await within(chrome.tabs.query({ windowId: opened.id }), 2_000);
  const blank = Array.isArray(blanked) ? blanked[0] : null;
  await within(chrome.tabs.move(tab.id, { windowId: opened.id, index: -1 }), 2_000);
  if (blank && blank.id !== tab.id) await chrome.tabs.remove(blank.id).catch(() => null);
  await chrome.storage.local.set({ [WINDOW_KEY]: opened.id });
  await minimizeWindow(opened.id);
  return (await chrome.tabs.get(tab.id).catch(() => null)) || tab;
}

async function resolveWorkTab(domains) {
  const tab = (await rememberedTab()) || (await adoptOwnedTab()) || (await createWorkTab());
  return (await isolateWorkTab(tab)) || tab;
}

async function replyTab(params, domains) {
  if (params && params.tab === "work") return workTab(domains);
  return activeTab();
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

// Watching for a gate page while the navigation is still in flight.
//
// A verification interstitial never fires the load event, so `waitComplete` sits out its whole
// budget on a page that is already final: measured 12.12 s on Wiley (2026-11-25), for an answer
// the document title had given away in about a second. `waitNavigated` has the same problem when
// the challenge is served at the article's own URL, because then the URL never moves.
//
// The markers arrive from the kernel (`core/risk.py`, via the `goto` params) and are opaque
// here: this file does not know what a gate page is, and must not grow a second copy of the
// list. The kernel still decides `blocked` / not-blocked with its stricter rule; this only ends
// the wait early.
const GATE_GRACE_MS = 1_500;
const GATE_POLL_MS = 250;
// Long enough to cover either wait above: the gate can appear while the URL is still settling.
const GATE_WATCH_MS = 13_000;

function gateMarkers(params) {
  const urls = Array.isArray(params.halt_url_markers) ? params.halt_url_markers : [];
  const titles = Array.isArray(params.halt_titles) ? params.halt_titles : [];
  const clean = (list) =>
    list.filter((marker) => typeof marker === "string" && marker).map((m) => m.toLowerCase());
  return { urls: clean(urls), titles: clean(titles) };
}

function looksLikeGate(tab, markers) {
  const url = String((tab && tab.url) || "").toLowerCase();
  if (url && markers.urls.some((marker) => url.includes(marker))) return true;
  const title = String((tab && tab.title) || "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
  // `startsWith`, not `includes`: the kernel's rule treats a marker as a gate title only when it
  // *is* the title or opens it (the rest being the site's name). Stopping on a looser match
  // would cost a pause on an article that merely mentions the words.
  return Boolean(title) && markers.titles.some((marker) => title.startsWith(marker));
}

function gateWatch(tabId, params) {
  // Resolves `true` once a gate marker has persisted for the grace period, `false` otherwise.
  // **`promise: null` means "there is nothing to watch"** — not "already false". A resolved
  // `false` looks the same to `await`, and the first version of this returned exactly that: the
  // race below then won instantly, both navigation waits were abandoned, and the read-back
  // answered `policy.domain` for a page that was merely still loading (measured 2026-11-25:
  // the first search after `wensu browser start` failed once and then worked).
  const markers = gateMarkers(params);
  let stopped = false;
  const stop = () => {
    stopped = true;
  };
  if (!markers.urls.length && !markers.titles.length) {
    return { promise: null, stop };
  }
  const promise = (async () => {
    const deadline = Date.now() + GATE_WATCH_MS;
    let matchingSince = 0;
    while (!stopped && Date.now() < deadline) {
      const tab = await chrome.tabs.get(tabId).catch(() => null);
      if (stopped) break;
      if (tab && looksLikeGate(tab, markers)) {
        // The grace is what keeps a challenge that solves *itself* cheap: its script runs
        // immediately, and a navigation that does resolve moves the tab away inside this
        // window — the marker then disappears and the ordinary wait carries on.
        if (!matchingSince) matchingSince = Date.now();
        else if (Date.now() - matchingSince >= GATE_GRACE_MS) return true;
      } else {
        matchingSince = 0;
      }
      await new Promise((resolve) => setTimeout(resolve, GATE_POLL_MS));
    }
    return false;
  })();
  return { promise, stop };
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
    if (action === "snapshot") {
      // Two shapes of the same verb: no `token` starts a capture, `token`+`offset` reads
      // the next chunk of it. The bytes never touch the download manager.
      const token = params && typeof params.token === "string" ? params.token : "";
      if (token) {
        const capture = captures.get(token);
        if (!capture) throw new Error("snapshot.expired");
        reply({
          ok: true,
          data: {
            token,
            total: capture.bytes.length,
            base64: sliceChunk(capture, Number(params.offset) || 0),
            url: capture.url,
            title: capture.title,
            captcha_visible: capture.captchaVisible,
          },
        });
        return;
      }

      // Deliberately not domain-scoped: the user already has this tab open and the verb
      // issues no request of its own (ADR 0018). `pageCapture` rejects browser pages, so
      // the scheme is checked here to return a specific error instead of an API throw.
      const tab = await replyTab(params, domains);
      if (!tab || !tab.id) throw new Error("no_active_tab");
      if (!tab.url || !/^https?:/i.test(tab.url)) throw new Error("policy.url_scheme");
      const blob = await chrome.pageCapture.saveAsMHTML({ tabId: tab.id });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      // A challenge page is the one thing this verb must not hand back as if it were the
      // article. Reading the flag costs one message at most and lets the caller say
      // "stop, solve it yourself" instead of summarising a captcha.
      const meta = await pageMeta(tab.id);
      const fresh = {
        token: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`,
        bytes,
        url: tab.url,
        title: tab.title || "",
        captchaVisible: meta.captcha_visible === true,
      };
      captures.set(fresh.token, fresh);
      // A capture nobody reads must not sit in memory forever.
      setTimeout(() => captures.delete(fresh.token), 120_000);
      reply({
        ok: true,
        data: {
          token: fresh.token,
          total: bytes.length,
          base64: sliceChunk(fresh, 0),
          url: fresh.url,
          title: fresh.title,
          captcha_visible: fresh.captchaVisible,
          status: Number(meta.status) || 0,
        },
      });
      return;
    }

    if (action === "goto") {
      // `open: "new"` opens a separate tab for this navigation; the next `goto` blanks it
      // (`close: "disposable"`) and continues in it, so a caller can chain two navigations
      // and still end up with exactly one tab of its own.
      if (params.open === "new") {
        const homeUrl = new URL(params.url);
        if (homeUrl.protocol !== "https:" || !allowedHost(homeUrl.hostname, domains)) {
          throw new Error("policy.domain");
        }
        await closeDisposableTabs();
        const began = Date.now();
        const created = await chrome.tabs.create({ url: params.url, active: true });
        await rememberDisposable(created && created.id);
        // `wait: "none"` returns as soon as the navigation is issued: the caller is going to
        // replace the tab's contents anyway, so waiting for the load event only delays it.
        if (params.wait !== "none") {
          await waitNavigated(created.id, "", domains).catch(() => null);
          await waitComplete(created.id).catch(() => null);
        }
        await new Promise((resolve) => setTimeout(resolve, dwellFor(params)));
        const updated = await chrome.tabs.get(created.id).catch(() => null);
        const where = (updated && updated.url) || params.url;
        return reply({
          ok: true,
          data: {
            url: where,
            title: (updated && updated.title) || "",
            transient: true,
          },
          duration_ms: Date.now() - began,
          url: where,
        });
      }
      let blanked = [];
      let halted = false;
      // Where the tab was before this action navigated it ("" for the `open: "new"` branch).
      let before = "";
      if (params.close === "disposable") blanked = await closeDisposableTabs();
      const tab = await workTab(domains);
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
        // The URL the tab was on when this action started. Kept out here because the read-back
        // below has to tell "a redirect took us somewhere else" (a policy event) apart from
        // "nothing moved yet" (not a policy event).
        before = tab.url || "";
        // Issue the navigation, then wait for it the way the page actually behaves. Wrapped in a
        // closure because Edge rejects the update on a work tab the previous run left behind
        // ("Navigation rejected."), and that is exactly the first navigation after a browser
        // start — measured 2026-11-25: the first search failed and the immediate retry worked.
        const navigate = async () => {
          await chrome.tabs.update(tab.id, { url: params.url });
          // Read the tab back only once it has moved: `tabs.get` immediately after
          // `update` can return the previous URL, which looked like a redirect out of scope.
          //
          // Bounded on purpose: a human-verification interstitial ("just a moment…") never
          // fires the load event, and the unbounded waits here outlasted the kernel's 15 s
          // budget — the caller was told `bridge.timeout` while the tab already showed the
          // challenge page. Reporting whatever is on screen lets the kernel classify it
          // (`blocked`), which is the honest answer and the one the risk rules describe
          // (2026-11-24, reproduced four times on a Cloudflare interstitial).
          const started = Date.now();
          // The gate watch runs beside both waits: an interstitial can be up before the URL moves
          // (the `waitNavigated` case) or after it moved but without ever finishing (`waitComplete`
          // case), and neither of those waits can see it. Whichever arrives first decides. With no
          // markers there is nothing to watch, and racing an already-resolved promise would throw
          // the waits away — that is why `gateWatch` returns `promise: null` there.
          const watch = gateWatch(tab.id, params);
          const navigated = (async () => {
            await within(waitNavigated(tab.id, before, domains), 10_000);
            // Whatever is left of a 13 s budget: heavy publisher pages genuinely need past 10 s
            // (Wiley measured 13.3 s), so this trims the tail of the *wait*, not the page.
            await within(waitComplete(tab.id), Math.max(1_000, 13_000 - (Date.now() - started)));
            return false;
          })();
          try {
            halted =
              watch.promise === null
                ? await navigated
                : await Promise.race([watch.promise, navigated]);
          } finally {
            watch.stop();
          }
        };
        try {
          await navigate();
        } catch (error) {
          // Only a rejected *update* is retried, not a failed wait: a page that did not load is
          // the site's business, while an update Edge refused on our own tab is ours. The caller
          // never sees this attempt, so a second one costs it nothing.
          await new Promise((resolve) => setTimeout(resolve, 300));
          await navigate();
        }
      }
      // A gate is the one thing a human has to look at, so its window comes back to the screen.
      // Unfocused on purpose: taking focus is exactly what keeps the windows minimized.
      if (halted) {
        await within(
          chrome.windows.update(tab.windowId, { state: "normal" }),
          1_000,
        ).catch(() => null);
      }
      if (params.reload === true) await within(waitComplete(tab.id), 3_000);
      await new Promise((resolve) => setTimeout(resolve, dwellFor(params)));

      let updated = await chrome.tabs.get(tab.id);
      let finalUrl = updated.url || params.url;
      // A tab that is not on an http(s) page after the navigation was not navigated at all. The
      // work tab can be in that state: the id remembered from the previous browser session points
      // at a blank tab Edge accepts `tabs.update` on and then does nothing with (measured
      // 2026-11-25, right after `wensu browser start`: `url: "about:blank"`, and the same request
      // worked a second later). Open a tab of our own instead of insisting — that is also what a
      // person does when a tab stops responding.
      const trail = { before, first: finalUrl, opened: null, after: finalUrl };
      if (params.reload !== true && !/^https?:/i.test(finalUrl)) {
        await new Promise((resolve) => setTimeout(resolve, 250));
        const opened = await chrome.tabs
          .create({ url: params.url, active: true })
          .catch(() => null);
        trail.opened = (opened && opened.id) || null;
        const target = opened && opened.id ? opened.id : tab.id;
        await within(waitNavigated(target, "", domains), 8_000);
        await within(waitComplete(target), 6_000);
        updated = await chrome.tabs.get(target).catch(() => updated);
        finalUrl = updated.url || params.url;
        trail.after = finalUrl;
      }
      const meta = await pageMeta(updated.id);
      const status = Number(meta.status || 0);
      // A URL that never left http(s) is not a domain violation: nothing was navigated. A
      // *changed* URL outside the scope still is a policy event (a login or verify redirect).
      //
      // "Unchanged" on its own is not enough: navigating to the document the tab is already on
      // (a search re-opening the advanced-search page, `page_read` re-reading the same article)
      // leaves the URL exactly as it was and is perfectly normal.
      const sameDoc = (one, two) => {
        try {
          const from = new URL(one);
          const to = new URL(two);
          return from.origin === to.origin && from.pathname === to.pathname;
        } catch {
          return false;
        }
      };
      const stalled =
        params.reload !== true &&
        before !== "" &&
        finalUrl === before &&
        !sameDoc(before, params.url);
      const outOfScope = !allowedHost(new URL(finalUrl).hostname, domains);
      const data = {
        ...meta,
        url: finalUrl,
        title: updated.title || "",
        status: status || undefined,
        // Reported only when it happened, so every existing caller reads the same shape it did
        // before this parameter existed.
        ...(halted ? { halted: true } : {}),
        // Reported so a caller can prove the tab was blanked and kept, rather than closed
        // and replaced by a new one.
        blanked,
      };
      if (stalled) {
        return reply({
          ok: false,
          error: "navigation.stalled",
          data: { ...data, diagnostics: trail },
        });
      }
      if (outOfScope || status >= 400) {
        // Refuse the navigation, but keep the final URL so the kernel can see
        // a login/verify redirect and persist the cooldown.
        return reply({
          ok: false,
          error: outOfScope ? "policy.domain" : `HTTP ${status}`,
          data: { ...data, diagnostics: trail },
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




