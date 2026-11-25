/* Probe the extension's tab lifecycle without a browser.
 *
 * Loads the real `extension/background.js` into a VM with a fake `chrome`, then drives the
 * same two `goto`s `read_page` sends and reports what the browser was asked to do.
 *
 * Prints one JSON object on stdout. Assertions live in the pytest wrapper
 * (tests/unit/test_extension_tab_lifecycle.py) so a failure reads like a Python test.
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const BG = process.env.WENSU_BACKGROUND_JS;
if (!BG) {
  console.log(JSON.stringify({ error: "WENSU_BACKGROUND_JS is not set" }));
  process.exit(0);
}

const saved = () => JSON.parse(JSON.stringify(observations));
const observations = {
  adopted_foreign_tab: null,
  adopted_tab_id: null,
  created_fallback_url: null,
  transient: {},
  work_tab: {},
};

function makeBrowser(seed = []) {
  const tabs = new Map();
  const requests = [];
  const session = new Map();
  const local = new Map();
  const windows = new Map([[1, { id: 1 }]]);
  let nextWindowId = 900;
  let nextId = 100;
  for (const tab of seed) {
    tabs.set(tab.id, { title: "", status: "complete", windowId: 1, ...tab });
  }

  const chrome = {
    runtime: {
      connectNative: () => ({
        onMessage: { addListener() {} },
        onDisconnect: { addListener() {} },
        postMessage() {},
        disconnect() {},
      }),
      onInstalled: { addListener() {} },
      onStartup: { addListener() {} },
      onMessage: { addListener() {} },
      getURL: (p) => `chrome-extension://test/${p}`,
      lastError: undefined,
    },
    storage: {
      session: {
        get: async (key) => ({ [key]: session.get(key) }),
        set: async (obj) => {
          for (const key of Object.keys(obj)) session.set(key, obj[key]);
        },
      },
      // `local` outlives a reload; a scenario seeds it to stand for "what the last run
      // remembered" while `session` starts empty, which is the state after a reload.
      local: {
        get: async (key) => ({ [key]: local.get(key) }),
        set: async (obj) => {
          for (const key of Object.keys(obj)) local.set(key, obj[key]);
        },
      },
    },
    tabs: {
      create: async (opts) => {
        const id = nextId++;
        const tab = {
          id,
          url: opts.url,
          status: "complete",
          active: opts.active !== false,
          windowId: opts.windowId || 1,
        };
        tabs.set(id, tab);
        requests.push(opts.url);
        return { ...tab };
      },
      get: async (id) => {
        if (!tabs.has(id)) throw new Error("no tab");
        return { ...tabs.get(id) };
      },
      query: async (filter) =>
        [...tabs.values()]
          .filter((tab) => !filter || filter.windowId === undefined || tab.windowId === filter.windowId)
          .map((tab) => ({ ...tab })),
      update: async (id, opts) => {
        const tab = tabs.get(id);
        if (!tab) throw new Error("no tab");
        if (opts.pinned !== undefined) tab.pinned = opts.pinned;
        if (opts.url) {
          tab.url = opts.url;
          requests.push(opts.url);
        }
        return { ...tab };
      },
      remove: async (id) => {
        if (!tabs.delete(id)) throw new Error("no tab");
      },
      move: async (id, opts) => {
        const tab = tabs.get(id);
        if (!tab) throw new Error("no tab");
        if (opts && opts.windowId) tab.windowId = opts.windowId;
        return { ...tab };
      },
      reload: async () => {},
      // `pageMeta` races this against a 1 s deadline; rejecting keeps the probe fast.
      sendMessage: async () => {
        throw new Error("no receiver");
      },
    },
    windows: {
      create: async (opts) => {
        const id = nextWindowId++;
        windows.set(id, { id, state: "normal" });
        const tabId = nextId++;
        const tab = {
          id: tabId,
          url: (opts && opts.url) || "about:blank",
          status: "complete",
          active: true,
          windowId: id,
        };
        tabs.set(tabId, tab);
        requests.push(tab.url);
        // Real Chromium answers with `{ id, type, ... }` and **no** `tabs` array: a caller
        // that reads `win.tabs[0]` throws, and the host never gets a reply (2026-11-24,
        // reproduced live as `bridge.timeout` at `navigate.open`).
        return { id };
      },
      get: async (id) => {
        if (!windows.has(id)) throw new Error("no window");
        return { ...windows.get(id) };
      },
      // The state is recorded, not ignored: the work window is supposed to be minimized so a
      // search never takes the screen, and the probe has to be able to see that.
      update: async (id, opts) => {
        if (!windows.has(id)) throw new Error("no window");
        const win = windows.get(id);
        if (opts && opts.state) win.state = opts.state;
        return { ...win };
      },
      getAll: async () => [...windows.values()].map((win) => ({ ...win })),
    },
    downloads: { onCreated: { addListener() {} }, search: async () => [] },
    scripting: { executeScript: async () => [{ result: {} }] },
    pageCapture: { saveAsMHTML: async () => ({}) },
  };
  return { chrome, tabs, requests, session, local, windows };
}

function load(browser) {
  const sandbox = {
    chrome: browser.chrome,
    console,
    setTimeout,
    clearTimeout,
    URL,
    Math,
    Date,
    JSON,
    Promise,
    Uint8Array,
    TextDecoder,
    crypto: { randomUUID: () => "00000000-0000-4000-8000-000000000000" },
  };
  const context = vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(BG, "utf8"), context, { filename: path.basename(BG) });
  return context;
}

function hostOf(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

const DOMAINS = ["onlinelibrary.wiley.com", "advanced.onlinelibrary.wiley.com"];
const ARTICLE = "https://advanced.onlinelibrary.wiley.com/doi/10.1002/adma.75384";
const FIRST_URL = "https://advanced.onlinelibrary.wiley.com/";

async function scenarioAdoption() {
  // A tab the user already had open on the same publisher, and no work tab remembered.
  const browser = makeBrowser([{ id: 7, url: ARTICLE }]);
  const context = load(browser);
  const tab = await context.workTab(DOMAINS);
  observations.adopted_foreign_tab = Boolean(tab && tab.id === 7);
  observations.adopted_tab_id = tab && tab.id;
}

async function scenarioFallback() {
  const browser = makeBrowser([]);
  const context = load(browser);
  const tab = await context.workTab(DOMAINS);
  observations.created_fallback_url = (tab && tab.url) || null;
}

async function scenarioAfterReload() {
  // The last run's memory lives in `local`; `session` is empty, which is the state after
  // the extension reloads. The tab it named is still open, so no second tab may appear.
  const browser = makeBrowser([{ id: 41, url: "about:blank" }]);
  browser.local.set("wensuWorkTabId", 41);
  browser.local.set("wensuWorkWindowId", 1);
  const context = load(browser);
  const before = browser.tabs.size;
  const tab = await context.workTab(DOMAINS);
  observations.reload = {
    tab_id: tab && tab.id,
    tabs_before: before,
    tabs_after: browser.tabs.size,
    created: browser.requests.filter((url) => url === "about:blank").length,
  };
}

async function scenarioStaleOwnedTabs() {
  // Two tabs an older build left behind and no remembered work id: adopt the newest and
  // remove the spare, so the count goes down instead of up.
  const browser = makeBrowser([
    { id: 51, url: "about:blank" },
    { id: 52, url: "about:blank" },
  ]);
  browser.local.set("wensuOwnedTabs", [51, 52]);
  browser.local.set("wensuWorkWindowId", 1);
  const context = load(browser);
  const tab = await context.workTab(DOMAINS);
  observations.orphans = {
    tab_id: tab && tab.id,
    remaining: [...browser.tabs.keys()],
  };
}

async function scenarioTransientTab() {
  const browser = makeBrowser([]);
  const context = load(browser);
  // The extension warms its work tab when it connects (that is what keeps the window
  // creation off the action path), so let that settle and then start from an empty browser:
  // this scenario drives the two-`goto` flow from scratch on purpose.
  await new Promise((resolve) => setTimeout(resolve, 25));
  browser.tabs.clear();
  browser.local.clear();
  browser.requests.length = 0;
  const replies = [];
  const channel = { postMessage: (payload) => replies.push(payload) };

  await context.onHostMessage(
    {
      type: "action",
      id: 1,
      action: "goto",
      params: { url: FIRST_URL, open: "new", dwell_ms: 1 },
      domains: DOMAINS,
    },
    channel,
  );
  const homeIds = [...browser.tabs.keys()];
  const homeId = homeIds[homeIds.length - 1];

  await context.onHostMessage(
    {
      type: "action",
      id: 2,
      action: "goto",
      params: { url: ARTICLE, close: "disposable" },
      domains: DOMAINS,
    },
    channel,
  );

  observations.transient = {
    first_tab_id: homeId,
    first_tab_survived: browser.tabs.has(homeId),
    first_tab_url_after: browser.tabs.has(homeId) ? browser.tabs.get(homeId).url : null,
    tabs_after: [...browser.tabs.values()].map((t) => ({ id: t.id, url: t.url })),
    requests: browser.requests.slice(),
    // `blanked` is the extension's own account of the transient tab: the tab is kept and
    // overwritten with about:blank, which the browser cannot show us after the fact — the
    // second `goto` blanks it and immediately loads the article in the same tab.
    replies: replies.map((reply) => ({
      ok: reply && reply.ok,
      blanked: (reply && reply.data && reply.data.blanked) || [],
      transient: Boolean(reply && reply.data && reply.data.transient),
    })),
    unexpected_hosts: browser.requests
      .map(hostOf)
      .filter((host) => host && !DOMAINS.some((d) => host === d || host.endsWith(`.${d}`))),
    replies_ok: replies.every((r) => r && r.ok !== false),
  };

  // Which tab ended up bound for later actions (a search must land there, not in the
  // user's own tab).
  const work = await context.workTab(DOMAINS);
  observations.work_tab = {
    id: work && work.id,
    url: work && work.url,
    window_id: work && work.windowId,
    pinned: Boolean(browser.tabs.get(work.id) && browser.tabs.get(work.id).pinned),
    // Keep out of the user's way: the work window is its own window and it stays minimized.
    window_state: work && work.windowId ? browser.windows.get(work.windowId).state : null,
  };

  // The boot-time sweep runs once per browser session. A window the user restored by hand must
  // stay restored: re-minimizing it under them is the sort of thing that makes a tool hated.
  const first = [...browser.windows.values()].map((win) => win.state);
  await context.quietWindows();
  const afterFirst = [...browser.windows.values()].map((win) => win.state);
  const restored = browser.windows.get(work.windowId);
  if (restored) restored.state = "normal"; // the user clicked the taskbar
  await context.quietWindows();
  observations.quiet = {
    before: first,
    after_first_call: afterFirst,
    after_second_call: [...browser.windows.values()].map((win) => win.state),
  };
}

(async () => {
  const watchdog = setTimeout(() => {
    console.log(JSON.stringify({ ...saved(), watchdog: true }));
    process.exit(0);
  }, 20000);
  try {
    await scenarioAdoption();
    await scenarioFallback();
    await scenarioAfterReload();
    await scenarioStaleOwnedTabs();
    await scenarioTransientTab();
  } catch (error) {
    observations.error = String((error && error.message) || error);
  }
  clearTimeout(watchdog);
  console.log(JSON.stringify(observations));
  process.exit(0);
})();
