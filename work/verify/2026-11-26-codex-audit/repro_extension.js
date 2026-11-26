/* Run the actual service worker with the repository's existing fake browser.
 * No browser is opened and no URL is contacted.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const root = path.resolve(__dirname, "../../..");
const manifest = JSON.parse(fs.readFileSync(path.join(root, "extension/manifest.json"), "utf8"));
process.env.WENSU_BACKGROUND_JS = path.join(root, "extension", manifest.background.service_worker);
const helper = fs.readFileSync(path.join(root, "tests/js/gate_watch_probe.js"), "utf8");
const prefix = helper.slice(0, helper.indexOf("async function scenarioRedirectOutOfScope()"));
const scenario = `
(async () => {
  const browser = makeBrowser();
  const context = load(browser);
  await sleep(25);
  await context.workTab(DOMAINS);
  let updates = 0;
  let waits = 0;
  const update = browser.chrome.tabs.update;
  browser.chrome.tabs.update = async (id, opts) => {
    if (opts.url === ARTICLE) updates += 1;
    return update(id, opts);
  };
  context.waitNavigated = async () => {
    waits += 1;
    if (waits === 1) throw new Error("synthetic_wait_failure_after_accepted_update");
    return null;
  };
  context.waitComplete = async () => null;
  const replies = [];
  await context.onHostMessage({type: "action", id: "audit-goto", action: "goto",
    params: {url: ARTICLE, dwell_ms: 0}, domains: DOMAINS},
    {postMessage: p => replies.push(p)});
  const navigation = replies.at(-1);
  const waitsReply = [];
  await context.onHostMessage({type: "action", id: "audit-wait", action: "wait_for",
    params: {selector: 'meta[name="citation_doi"]', timeout_ms: 2000}, domains: DOMAINS},
    {postMessage: p => waitsReply.push(p)});
  console.log(JSON.stringify({
    one_goto_accepted_updates: updates,
    wait_calls: waits,
    goto_result_ok: navigation.ok,
    goto_reports_retry: Object.hasOwn(navigation.data || {}, "retry"),
    publisher_wait_without_content_script: waitsReply.at(-1),
  }, null, 2));
  process.exit(0);
})().catch(error => {console.error(error); process.exit(1);});
`;
vm.runInNewContext(prefix + scenario, {
  require, process, console, setTimeout, clearTimeout, URL,
  Uint8Array, TextDecoder,
});
