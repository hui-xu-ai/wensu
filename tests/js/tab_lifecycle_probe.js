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
  referrer: {},
  work_tab: {},
};

function makeBrowser(seed = []) {
  const tabs = new Map();
  const requests = [];
  const session = new Map();
  let nextId = 100;
  for (const tab of seed) tabs.set(tab.id, { title: "", status: "complete", ...tab });

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
    },
    tabs: {
      create: async (opts) => {
        const id = nextId++;
        const tab = { id, url: opts.url, status: "complete", active: opts.active !== false };
        tabs.set(id, tab);
        requests.push(opts.url);
        return { ...tab };
      },
      get: async (id) => {
        if (!tabs.has(id)) throw new Error("no tab");
        return { ...tabs.get(id) };
      },
      query: async () => [...tabs.values()].map((tab) => ({ ...tab })),
      update: async (id, opts) => {
        const tab = tabs.get(id);
        if (!tab) throw new Error("no tab");
        if (opts.url) {
          tab.url = opts.url;
          requests.push(opts.url);
        }
        return { ...tab };
      },
      remove: async (id) => {
        if (!tabs.delete(id)) throw new Error("no tab");
      },
      reload: async () => {},
      // `pageMeta` races this against a 1 s deadline; rejecting keeps the probe fast.
      sendMessage: async () => {
        throw new Error("no receiver");
      },
    },
    downloads: { onCreated: { addListener() {} }, search: async () => [] },
    scripting: { executeScript: async () => [{ result: {} }] },
    pageCapture: { saveAsMHTML: async () => ({}) },
  };
  return { chrome, tabs, requests, session };
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
const HOMEPAGE = "https://advanced.onlinelibrary.wiley.com/";

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

async function scenarioReferrerHop() {
  const browser = makeBrowser([]);
  const context = load(browser);
  const replies = [];
  const channel = { postMessage: (payload) => replies.push(payload) };

  await context.onHostMessage(
    {
      type: "action",
      id: 1,
      action: "goto",
      params: { url: HOMEPAGE, open: "new", dwell_ms: 1 },
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

  observations.referrer = {
    home_tab_id: homeId,
    home_tab_survived: browser.tabs.has(homeId),
    home_tab_url_after: browser.tabs.has(homeId) ? browser.tabs.get(homeId).url : null,
    tabs_after: [...browser.tabs.values()].map((t) => ({ id: t.id, url: t.url })),
    requests: browser.requests.slice(),
    // `blanked` is the extension's own account of the front-page tab: the tab is kept and
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
  observations.work_tab = { id: work && work.id, url: work && work.url };
}

(async () => {
  const watchdog = setTimeout(() => {
    console.log(JSON.stringify({ ...saved(), watchdog: true }));
    process.exit(0);
  }, 20000);
  try {
    await scenarioAdoption();
    await scenarioFallback();
    await scenarioReferrerHop();
  } catch (error) {
    observations.error = String((error && error.message) || error);
  }
  clearTimeout(watchdog);
  console.log(JSON.stringify(observations));
  process.exit(0);
})();
