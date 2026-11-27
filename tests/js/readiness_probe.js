/* Observation mode without a browser (ADR 0031).
 *
 * Loads the real `extension/background-<version>.js` into a VM with a fake `chrome`, then asks it
 * to observe a tab whose metadata follows a script. What matters:
 *
 *   candidate   a complete tab that stopped changing is reported as a candidate;
 *   late        a tab that never settles reports `observing` with `budget_exhausted`, never a
 *               verdict about the page;
 *   no_bytes    `pageCapture.saveAsMHTML` is called **zero** times — observation produces no file.
 *
 * Prints one JSON object; the assertions live in the pytest wrapper.
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const BG = process.env.WENSU_BACKGROUND_JS;
if (!BG) {
  console.log(JSON.stringify({ error: "WENSU_BACKGROUND_JS is not set" }));
  process.exit(0);
}

const DOMAINS = ["www.sciencedirect.com"];
const ARTICLE = "https://www.sciencedirect.com/science/article/pii/S1385894723029534";

function listener() {
  return { addListener() {} };
}

function makeChrome(script) {
  let captures = 0;
  let step = 0;
  const chrome = {
    runtime: {
      id: "probe",
      onInstalled: listener(),
      onStartup: listener(),
      onConnect: listener(),
      onMessage: listener(),
      getManifest: () => ({ version: "0.0.0-probe", background: {} }),
      sendMessage: async () => undefined,
    },
    storage: {
      local: { get: async () => ({}), set: async () => undefined },
      session: { get: async () => ({}), set: async () => undefined },
    },
    tabs: {
      query: async () => [current()],
      get: async () => current(),
      update: async () => current(),
      create: async () => current(),
      remove: async () => undefined,
      onUpdated: listener(),
      onRemoved: listener(),
    },
    windows: {
      get: async () => ({ id: 1, state: "normal" }),
      update: async () => ({ id: 1, state: "normal" }),
      getAll: async () => [{ id: 1, state: "normal" }],
      create: async () => ({ id: 1 }),
      remove: async () => undefined,
      onCreated: listener(),
      onRemoved: listener(),
      onFocusChanged: listener(),
    },
    alarms: { create() {}, clear: async () => undefined, onAlarm: listener() },
    action: { onClicked: listener() },
    permissions: { contains: async () => true },
    downloads: { onCreated: listener(), search: async () => [], download: async () => 1 },
    scripting: { executeScript: async () => [{ result: {} }] },
    pageCapture: {
      saveAsMHTML: async () => {
        captures += 1;
        return { size: 1, arrayBuffer: async () => new ArrayBuffer(1) };
      },
    },
  };
  function current() {
    const entry = script[Math.min(step, script.length - 1)];
    step += 1;
    return { id: 7, windowId: 1, ...entry };
  }
  return { chrome, captures: () => captures };
}

function load(chrome) {
  const sandbox = {
    chrome,
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

async function send(context, message) {
  const replies = [];
  const channel = { postMessage: (payload) => replies.push(payload) };
  await context.onHostMessage(message, channel);
  return replies[replies.length - 1] || null;
}

async function observe(script, budgetMs) {
  const { chrome, captures } = makeChrome(script);
  const context = load(chrome);
  const hello = await send(context, { type: "hello", id: 1, protocol: 1, domains: DOMAINS });
  const reply = await send(context, {
    type: "action",
    id: 2,
    action: "snapshot",
    params: { mode: "observe", observe_ms: budgetMs },
    domains: DOMAINS,
  });
  return { hello, reply, captures: captures() };
}

(async () => {
  const out = {};

  // A tab that finishes loading and then holds still: the first two reads say `loading`.
  out.candidate = await observe(
    [
      { status: "loading", url: ARTICLE, title: "ScienceDirect" },
      { status: "loading", url: ARTICLE, title: "ScienceDirect" },
      { status: "complete", url: ARTICLE, title: "The article" },
      { status: "complete", url: ARTICLE, title: "The article" },
      { status: "complete", url: ARTICLE, title: "The article" },
      { status: "complete", url: ARTICLE, title: "The article" },
    ],
    2_000,
  );

  // A tab that never settles: the answer must not claim anything about the page.
  out.late = await observe([{ status: "loading", url: ARTICLE, title: "请稍候…" }], 900);

  console.log(JSON.stringify(out));
  // Explicit: the worker registers listeners and timers, and an idle VM would keep node alive.
  process.exit(0);
})();
