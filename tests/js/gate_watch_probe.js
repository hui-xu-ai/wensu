/* Probe the gate watcher without a browser.
 *
 * Loads the real `extension/background.js` into a VM with a fake `chrome`, drives the very
 * `goto` that `page_read` sends, and reports how long the reply took and what it said.
 *
 * Three shapes, all of them seen or reported on a live publisher in 2026-11-25:
 *
 *   wall      the interstitial keeps `status: "loading"` forever and its title is 「请稍候…」
 *             (measured: 12.12 s of waiting, 0 bytes captured);
 *   solved    a challenge that clears itself: the title and status settle on the article;
 *   plain     no markers at all — the old behaviour, which must be byte-for-byte unchanged.
 *
 * Prints one JSON object on stdout. Assertions live in the pytest wrapper
 * (tests/unit/test_wall_early_exit.py) so a failure reads like a Python test.
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const BG = process.env.WENSU_BACKGROUND_JS;
if (!BG) {
  console.log(JSON.stringify({ error: "WENSU_BACKGROUND_JS is not set" }));
  process.exit(0);
}

const DOMAINS = ["onlinelibrary.wiley.com", "advanced.onlinelibrary.wiley.com"];
const ARTICLE = "https://advanced.onlinelibrary.wiley.com/doi/10.1002/adma.75384";
const WALL_TITLE = "请稍候…";
const ARTICLE_TITLE = "A Multifunctional Ionograsper";

// The markers `ScholarService._page_goto_params` sends: opaque strings, straight from
// `core/risk.py`.
const HALT = {
  halt_url_markers: ["/verify/home", "/verify/", "captcha", "recaptcha", "hcaptcha"],
  halt_titles: ["just a moment", "请稍候", "verifying you are human", "checking your browser"],
};

function makeBrowser() {
  const tabs = new Map();
  const session = new Map();
  const local = new Map();
  let nextId = 100;
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
    // Real storage matters here: the work tab is remembered in it, so a stub that forgets
    // would make the second `workTab()` call create a different tab — and the probe would
    // then mutate a tab the navigation never touched.
    storage: {
      session: {
        get: async (key) => ({ [key]: session.get(key) }),
        set: async (obj) => {
          for (const key of Object.keys(obj)) session.set(key, obj[key]);
        },
      },
      local: {
        get: async (key) => ({ [key]: local.get(key) }),
        set: async (obj) => {
          for (const key of Object.keys(obj)) local.set(key, obj[key]);
        },
      },
    },
    tabs: {
      create: async (opts) => {
        const tab = {
          id: nextId++,
          url: opts.url,
          status: "complete",
          title: "",
          active: opts.active !== false,
          windowId: opts.windowId || 1,
        };
        tabs.set(tab.id, tab);
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
        if (opts.url) tab.url = opts.url;
        return { ...tab };
      },
      remove: async (id) => {
        tabs.delete(id);
      },
      move: async (id, opts) => {
        const tab = tabs.get(id);
        if (opts && opts.windowId) tab.windowId = opts.windowId;
        return { ...tab };
      },
      reload: async () => {},
      sendMessage: async () => {
        throw new Error("no receiver");
      },
    },
    windows: {
      create: async () => ({ id: 900, state: "normal" }),
      get: async (id) => ({ id, state: windowState.get(id) || "normal" }),
      // Recorded, because a gate is the one case that brings the window back: a human has to
      // look at the challenge page, so it may not stay minimized.
      update: async (id, opts) => {
        if (opts && opts.state) windowState.set(id, opts.state);
        return { id, state: windowState.get(id) || "normal" };
      },
      getAll: async () => [{ id: 900, state: windowState.get(900) || "normal" }],
      onCreated: {
        listeners: [],
        addListener(fn) {
          this.listeners.push(fn);
        },
      },
    },
    downloads: { onCreated: { addListener() {} }, search: async () => [] },
    scripting: { executeScript: async () => [{ result: {} }] },
    pageCapture: { saveAsMHTML: async () => ({}) },
  };
  return { chrome, tabs };
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

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Window states, keyed by window id. The extension minimizes its work window and brings it back
// when a gate needs a human, so the probes have to see both.
const windowState = new Map();

async function drive(params, schedule) {
  const browser = makeBrowser();
  const context = load(browser);
  // The extension warms its own tab when it connects; let that settle, then drive the
  // navigation on the tab it decided to use.
  await sleep(25);
  const work = await context.workTab(DOMAINS);
  const tabId = work.id;
  schedule(browser.tabs.get(tabId), browser);
  const replies = [];
  const channel = { postMessage: (payload) => replies.push(payload) };
  const began = Date.now();
  await context.onHostMessage(
    { type: "action", id: 1, action: "goto", params, domains: DOMAINS },
    channel,
  );
  const elapsed = Date.now() - began;
  const reply = replies[replies.length - 1] || {};
  const winId = work && work.windowId;
  return {
    elapsed_ms: elapsed,
    ok: reply.ok !== false,
    error: reply.error || null,
    halted: Boolean(reply.data && reply.data.halted),
    title: (reply.data && reply.data.title) || null,
    url: (reply.data && reply.data.url) || null,
    // The work window is minimized normally; a gate brings it back because a human has to look.
    window_state: winId ? windowState.get(winId) || "normal" : null,
  };
}

async function scenarioAlreadyThere() {
  // Navigating to the document the tab is already on: the URL does not change, and that is not a
  // stalled navigation — a search re-opens the advanced-search page and `page_read` re-reads the
  // same article all the time. (Found by the diagnostic trail itself: the first version of the
  // stall check called this `navigation.stalled`.)
  return drive({ url: ARTICLE, dwell_ms: 0 }, (tab, browser) => {
    tab.url = ARTICLE;
    tab.status = "complete";
    tab.title = ARTICLE_TITLE;
    browser.chrome.tabs.update = async () => ({ ...tab });
  });
}

async function scenarioStaysBlank() {
  // The update is *accepted* and nothing happens: the work tab stays on `about:blank`, which is
  // what the live run showed right after a browser start (`policy.domain` in 330 ms with
  // `url: "about:blank"`). A tab that is not on an http(s) page after the navigation has not been
  // navigated at all, so the answer must be one more attempt — not a policy verdict.
  return drive({ url: ARTICLE, dwell_ms: 0 }, (tab, browser) => {
    const update = browser.chrome.tabs.update;
    tab.status = "complete";
    tab.title = "about:blank";
    // This tab never navigates, whatever it is asked to do — the state the live run showed.
    browser.chrome.tabs.update = async (id, opts) => {
      if (opts && opts.url && id === tab.id) return { ...tab };
      return update(id, opts);
    };
  });
}

async function scenarioRejectedUpdate() {
  // Edge answers `tabs.update` on a work tab the previous run left behind with
  // "Navigation rejected.". The tab is ours and the target is in scope, so one retry is the
  // right answer — this is the second half of the 2026-11-25 symptom ("first search after a
  // browser start fails, the retry works"), reproduced here as a rejected first update.
  return drive({ url: ARTICLE, dwell_ms: 0 }, (tab, browser) => {
    let navigations = 0;
    const update = browser.chrome.tabs.update;
    browser.chrome.tabs.update = async (id, opts) => {
      // Only the *navigation* is rejected: `tabs.update` also pins and moves tabs, and a retry
      // that swallowed those would be a different bug.
      if (opts && opts.url) {
        navigations += 1;
        if (navigations === 1) throw new Error("Navigation rejected.");
      }
      const answered = await update(id, opts);
      tab.status = "complete";
      tab.title = ARTICLE_TITLE;
      return answered;
    };
  });
}

async function scenarioLateCommit() {
  // A navigation commits a moment after it is asked for, and the old page is still what the
  // tab reports. With no gate markers there is nothing to watch, and the first version of the
  // gate watch raced the real wait against an already-resolved "no gate" promise: the race
  // won instantly, both waits were abandoned, and the read-back answered `policy.domain` for a
  // page that was simply still loading (measured 2026-11-25: the first search after
  // `wensu browser start` failed once and then worked).
  return drive({ url: ARTICLE, dwell_ms: 0 }, (tab, browser) => {
    const update = browser.chrome.tabs.update;
    tab.title = "";
    tab.status = "loading";
    // Issue the navigation at once and let the document arrive later, the way a real browser
    // does: `tabs.update` answers immediately, the commit is the network's business. The old
    // page stays what the tab reports until then.
    browser.chrome.tabs.update = (id, opts) => {
      setTimeout(() => {
        tab.url = opts.url;
        tab.status = "complete";
        tab.title = ARTICLE_TITLE;
      }, 2_500);
      return Promise.resolve({ ...tab });
    };
  });
}

async function scenarioWall() {
  // Never completes: this is what an interstitial does, and what cost 12.12 s on 2026-11-25.
  // The tab is put in that state *before* the navigation is driven, because a real navigation
  // is in `loading` from its first millisecond — a tab that reports "complete" while the
  // document is the wall is not a shape this browser produces.
  return drive({ url: ARTICLE, dwell_ms: 0, ...HALT }, (tab) => {
    tab.title = WALL_TITLE;
    tab.status = "loading";
  });
}

async function scenarioSolvedItself() {
  // A challenge that clears: the marker is up briefly, then the article settles.
  return drive({ url: ARTICLE, dwell_ms: 0, ...HALT }, (tab) => {
    tab.title = WALL_TITLE;
    tab.status = "loading";
    setTimeout(() => {
      tab.title = ARTICLE_TITLE;
      tab.status = "complete";
    }, 600);
  });
}

async function scenarioPlain() {
  // No markers: a page that loads normally must behave exactly as before.
  return drive({ url: ARTICLE, dwell_ms: 0 }, (tab) => {
    tab.title = ARTICLE_TITLE;
    tab.status = "complete";
  });
}

(async () => {
  const observations = {};
  const watchdog = setTimeout(() => {
    console.log(JSON.stringify({ ...observations, watchdog: true }));
    process.exit(0);
  }, 30000);
  try {
    observations.already_there = await scenarioAlreadyThere();
    observations.stays_blank = await scenarioStaysBlank();
    observations.rejected = await scenarioRejectedUpdate();
    observations.late_commit = await scenarioLateCommit();
    observations.wall = await scenarioWall();
    observations.solved = await scenarioSolvedItself();
    observations.plain = await scenarioPlain();
  } catch (error) {
    observations.error = String((error && error.message) || error);
  }
  clearTimeout(watchdog);
  console.log(JSON.stringify(observations));
  process.exit(0);
})();
