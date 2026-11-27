/* The worker's lease fence, driven for real (docs/protocol-lease.md §5, plan P2 point 3).
 *
 * Loads the real `extension/background-<version>.js` into a VM with a fake `chrome` and drives
 * `onHostMessage` directly — the pattern that works (`gate_watch_probe.js`, `readiness_probe.js`).
 *
 *   sync_ack   `lease_sync` is acknowledged with the epoch and the fence the worker now holds
 *   stale      an action whose envelope carries an older fence is refused with `policy.fence`
 *   legacy     an action with no envelope still runs (older kernels send none)
 *   fresh      an action at the current fence still runs — the fence is not a wall
 *
 * Prints one JSON object; assertions live in the pytest wrapper.
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

function makeChrome() {
  const tab = { id: 7, windowId: 1, status: "complete", url: ARTICLE, title: "An article" };
  return {
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
      query: async () => [tab],
      get: async () => tab,
      update: async () => tab,
      create: async () => tab,
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
    pageCapture: { saveAsMHTML: async () => ({ arrayBuffer: async () => new ArrayBuffer(1) }) },
  };
}

function load() {
  const sandbox = {
    chrome: makeChrome(),
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

(async () => {
  const context = load();
  const out = {};

  out.hello = await send(context, { type: "hello", id: 1, protocol: 1, domains: DOMAINS });
  out.sync_ack = await send(context, {
    type: "lease_sync",
    id: 2,
    lease_id: "L1",
    fence: 5,
  });

  // A frame from the lease that was superseded (fence 4 < 5): must not touch the tab.
  out.stale = await send(context, {
    type: "action",
    id: 3,
    action: "snapshot",
    params: { mode: "observe", observe_ms: 300 },
    domains: DOMAINS,
    context: { version: 1, lease_id: "L0", fence: 4 },
  });

  // An older kernel sends no envelope at all; that must keep working.
  out.legacy = await send(context, {
    type: "action",
    id: 4,
    action: "sleep",
    params: { ms: 1 },
    domains: DOMAINS,
  });

  // The current lease is not fenced out of its own tab.
  out.fresh = await send(context, {
    type: "action",
    id: 5,
    action: "sleep",
    params: { ms: 1 },
    domains: DOMAINS,
    context: { version: 1, lease_id: "L1", fence: 5 },
  });

  console.log(JSON.stringify(out));
  // Explicit: the worker registers listeners and timers; an idle VM would keep node alive.
  process.exit(0);
})();
