/* scholar-search bridge — service worker.
 *
 * Relays actions from the native host to one bound tab. The extension only
 * accepts hosts inside its configured scope (the selected channel); the kernel
 * and native host enforce the same list independently.
 */

const HOST_NAME = "com.scholar.search";
const PROTOCOL_VERSION = 1;
const DEFAULT_DOMAINS = [
  "kns.cnki.net",
  "www.cnki.net",
  "webofscience.clarivate.cn",
  "www.webofscience.com",
];

let port = null;
let boundTabId = null;

function connect() {
  if (port) return;
  try {
    const channel = chrome.runtime.connectNative(HOST_NAME);
    port = channel;
    channel.onMessage.addListener((message) => onHostMessage(message, channel));
    channel.onDisconnect.addListener(() => {
      if (port === channel) port = null;
      setTimeout(connect, 3000);
    });
  } catch (error) {
    port = null;
    setTimeout(connect, 3000);
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

    // document_idle injection can lag behind a navigation; retry a missing
    // receiver before giving up.
    const sendToTab = async () => {
      for (let attempt = 0; attempt < 6; attempt += 1) {
        try {
          return await chrome.tabs.sendMessage(tabId, message);
        } catch (error) {
          const text = String((error && error.message) || error);
          // A navigation tears down the content script mid-flight. All three
          // wordings mean "the new document is not ready yet", not "the page is
          // broken", so they are retried rather than surfaced.
          if (!/Receiving end|Could not establish|message channel closed/i.test(text)) {
            throw error;
          }
          await new Promise((resolve) => setTimeout(resolve, 300));
        }
      }
      throw new Error("content_not_ready");
    };

    let result;
    if (action === "click") {
      // A navigational click can destroy the content-script context before it
      // replies, so a lost reply means "navigation started". Only that counts:
      // a missing element or a refusal must surface, or the caller sees success
      // for a click that never happened.
      try {
        result = await Promise.race([
          sendToTab(),
          new Promise((resolve) => setTimeout(() => resolve(undefined), 2000)),
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
        return reply({ ok: true, data: { navigation_expected: true } });
      }
    } else {
      result = await sendToTab();
    }
    if (!result) throw new Error("dom_failed");
    return reply({ ok: Boolean(result.ok), error: result.error, data: result.data || {} });
  } catch (error) {
    return reply({ ok: false, error: String((error && error.message) || error) });
  }
}

chrome.runtime.onInstalled.addListener(connect);
chrome.runtime.onStartup.addListener(connect);
connect();




