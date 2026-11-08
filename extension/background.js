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

function waitComplete(tabId, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const tab = await chrome.tabs.get(tabId);
        if (tab.status === "complete") return resolve();
      } catch (error) {
        return reject(error);
      }
      if (Date.now() > deadline) return reject(new Error("timeout.navigation"));
      setTimeout(tick, 250);
    };
    tick();
  });
}

async function pageMeta(tabId) {
  try {
    const result = await chrome.tabs.sendMessage(tabId, { type: "meta" });
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
        // The F5 the user would press: the result page is then built in one pass
        // instead of being filled in lazily as it scrolls.
        await chrome.tabs.reload(tab.id);
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
    if (boundTabId !== null) {
      const current = await chrome.tabs.get(tabId).catch(() => null);
      if (!current || !allowedHost(new URL(current.url).hostname, domains)) {
        throw new Error("policy.tab_scope");
      }
    }

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
      // replies. Treat a lost reply as "navigation started"; the plan's
      // following wait_for verifies the page.
      try {
        result = await Promise.race([
          sendToTab(),
          new Promise((resolve) => setTimeout(() => resolve(undefined), 2000)),
        ]);
      } catch (error) {
        result = undefined;
      }
      if (result === undefined) {
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




