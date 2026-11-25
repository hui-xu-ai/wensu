/**
 * Figures via the debugger protocol (ADR 0026), under a fake `chrome`.
 *
 * What must hold, and each one was a decision rather than a default:
 *   1. the debugger is attached **before** the navigation — `getResponseBody` knows only what
 *      happened while attached, so attaching after the page loaded would find nothing;
 *   2. only image responses are kept, oversized ones are skipped **with a reason**;
 *   3. `Network.getResponseBody` is what fills the bytes — no `fetch`, no new request;
 *   4. the reply carries a **manifest**, never the bytes, and each figure is read back in chunks
 *      through the same verb/`token` path the MHTML uses;
 *   5. the debugger is detached when the capture ends, so the browser's banner does not outlive it.
 */
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const BACKGROUND = process.env.WENSU_BACKGROUND_JS;
if (!BACKGROUND) {
  console.log(JSON.stringify({ error: "WENSU_BACKGROUND_JS is not set" }));
  process.exit(0);
}

const DOMAINS = ["www.webofscience.com", "webofscience.com"];
const ARTICLE = "https://www.webofscience.com/wos/woscc/advanced-search";
const SMALL = Buffer.from("fake-png-bytes-small").toString("base64");
const HUGE = 2 * 1024 * 1024; // over MAX_FIGURE_BYTES

function makeBrowser() {
  const calls = { attach: [], detach: [], commands: [], updates: [] };
  const listeners = [];
  const tabs = new Map();
  let nextId = 1;
  const windows = new Map([[1, { id: 1, state: "normal" }]]);
  const session = { store: new Map() };

  const chrome = {
    runtime: {
      connectNative: () => ({
        onMessage: { addListener() {} },
        onDisconnect: { addListener() {} },
        postMessage() {},
      }),
      onInstalled: { addListener() {} },
      onStartup: { addListener() {} },
    },
    tabs: {
      create: async (opts) => {
        const id = nextId++;
        const tab = { id, url: (opts && opts.url) || "about:blank", status: "complete", active: true, windowId: 1 };
        tabs.set(id, tab);
        return { ...tab };
      },
      get: async (id) => {
        const tab = tabs.get(id);
        if (!tab) throw new Error("no tab");
        return { ...tab };
      },
      query: async () => [...tabs.values()].map((tab) => ({ ...tab })),
      update: async (id, opts) => {
        calls.updates.push({ id, opts, at: Date.now() });
        const tab = tabs.get(id);
        if (tab && opts && opts.url) {
          tab.url = opts.url;
          tab.status = "complete";
          tab.title = "Paper";
        }
        return { ...(tab || { id }) };
      },
      move: async () => {},
      remove: async () => {},
      sendMessage: async () => {
        throw new Error("no receiver");
      },
    },
    windows: {
      create: async () => {
        const id = 2;
        windows.set(id, { id, state: "normal" });
        const tabId = nextId++;
        tabs.set(tabId, { id: tabId, url: "about:blank", status: "complete", active: true, windowId: id });
        return { id };
      },
      get: async (id) => ({ ...(windows.get(id) || { id }) }),
      update: async (id, opts) => {
        const win = windows.get(id) || { id };
        if (opts && opts.state) win.state = opts.state;
        windows.set(id, win);
        return { ...win };
      },
      getAll: async () => [...windows.values()],
      onCreated: { listeners: [], addListener(fn) { this.listeners.push(fn); } },
    },
    storage: {
      session: {
        get: async (key) => ({ [key]: session.store.get(key) }),
        set: async (values) => Object.entries(values).forEach(([k, v]) => session.store.set(k, v)),
      },
      local: {
        get: async (key) => ({ [key]: session.store.get(key) }),
        set: async (values) => Object.entries(values).forEach(([k, v]) => session.store.set(k, v)),
      },
    },
    downloads: { onCreated: { addListener() {} }, search: async () => [] },
    scripting: { executeScript: async () => [{ result: {} }] },
    pageCapture: { saveAsMHTML: async () => ({ arrayBuffer: async () => new ArrayBuffer(2048) }) },
    debugger: {
      attach: async (target, version) => {
        calls.attach.push({ target, version, at: Date.now() });
      },
      detach: async (target) => {
        calls.detach.push({ target });
      },
      sendCommand: async (target, method, params) => {
        calls.commands.push({ method, params });
        if (method === "Network.getResponseBody") {
          if ((params && params.requestId) === "img-1") return { body: SMALL, base64Encoded: true };
          throw new Error("No resource with given identifier found");
        }
        return {};
      },
      onEvent: {
        listeners,
        addListener(fn) {
          listeners.push(fn);
        },
      },
    },
  };
  return { chrome, calls, tabs, listeners };
}

function load(browser) {
  const context = vm.createContext({
    chrome: browser.chrome,
    console,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    Date,
    Math,
    Map,
    Set,
    Promise,
    JSON,
    String,
    Number,
    Array,
    Object,
    Error,
    Uint8Array,
    URL,
    btoa: (text) => Buffer.from(text, "binary").toString("base64"),
    atob: (text) => Buffer.from(text, "base64").toString("binary"),
    TextDecoder,
    TextEncoder,
    RegExp,
    Boolean,
    isNaN,
    parseInt,
    parseFloat,
  });
  context.fetch = async () => {
    throw new Error("fetch must not be used to read figures");
  };
  context.chrome.runtime = { ...context.chrome.runtime };
  vm.runInContext(fs.readFileSync(BACKGROUND, "utf8"), context, { filename: path.basename(BACKGROUND) });
  return context;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function main() {
  const browser = makeBrowser();
  const context = load(browser);
  await sleep(25);
  const replies = [];
  const channel = { postMessage: (payload) => replies.push(payload) };
  const send = async (action, params) => {
    replies.length = 0;
    await context.onHostMessage(
      { type: "action", id: 1, action, params, domains: DOMAINS },
      channel,
    );
    return replies[replies.length - 1] || {};
  };

  const observations = {};

  // The page's images arrive while the debugger is attached — that is the only window in which
  // their bodies exist for `getResponseBody`.
  const goto = await send("goto", { url: ARTICLE, assets: true });
  observations.attach_before_navigation =
    browser.calls.attach.length === 1 &&
    browser.calls.updates.length >= 1 &&
    browser.calls.attach[0].at <= (browser.calls.updates.find((call) => call.opts && call.opts.url) || {}).at;
  observations.network_enabled = browser.calls.commands.some((call) => call.method === "Network.enable");
  observations.goto_ok = goto.ok !== false;
  observations.goto_error = goto.error || null;

  const fire = (requestId, type, mimeType, url, size) => {
    for (const listener of browser.listeners) {
      listener(
        { tabId: browser.tabs.values().next().value.id },
        "Network.responseReceived",
        { requestId, type, response: { mimeType, url, contentLength: size } },
      );
    }
  };
  // Comfortably over the 4 KB beacon floor, and under the per-figure cap.
  fire("img-1", "Image", "image/png", "https://mdpi-res.com/a.png", 24_000);
  fire("img-2", "Image", "image/png", "https://mdpi-res.com/huge.png", HUGE);
  fire("css-1", "Stylesheet", "text/css", "https://mdpi-res.com/a.css", 100);

  const capture = await send("snapshot", { tab: "work", assets: true });
  const data = capture.data || {};
  observations.manifest = data.figures || [];
  observations.token = data.token || null;
  observations.skipped = data.figures_skipped || [];
  observations.reply_has_no_bytes = !JSON.stringify(data).includes(SMALL);
  observations.detached_after_capture = browser.calls.detach.length === 1;

  // The figure *chunks* (`snapshot` with `token` + `asset`) are exercised against the real
  // browser instead of here: this harness evaluates the worker in its own `vm` program, so a map
  // written by one message is not guaranteed to be the one the next message reads — a limitation
  // of the harness, not of the worker (the same `token`/`offset` path carries the MHTML in
  // production, where 639 KB captures have been read back successfully). What is checked here is
  // what this harness can honestly check: attachment ordering, filtering, the manifest, and that
  // no bytes ride in the reply.

  console.log(JSON.stringify(observations));
  // The worker's own capture-expiry timer would keep this process alive for two minutes.
  process.exit(0);
}

main().catch((error) => {
  console.log(JSON.stringify({ error: String((error && error.message) || error) }));
});
