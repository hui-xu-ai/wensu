"use strict";
// Executes the actual retry block in a Node VM with fake browser APIs. No networking.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const crypto = require("node:crypto");

async function main() {
  const file = path.resolve(__dirname, "../../..", "extension/background-0.14.31.js");
  const source = fs.readFileSync(file, "utf8").replace(/\r\n/g, "\n");
  const start = source.indexOf("const navigate = async () => {");
  const end = source.indexOf("\n      }\n      // A gate", start);
  if (start < 0 || end <= start) throw new Error("Retry block markers changed");
  const block = source.slice(start, end);
  if (!block.includes("await chrome.tabs.update") || !block.includes("await navigate();")) {
    throw new Error("Not the expected production block");
  }
  const calls = [];
  const waits = [];
  let movementChecks = 0;
  const context = vm.createContext({
    Date, Math, Error,
    tab: { id: 17 }, before: "about:blank", domains: ["example.invalid"],
    params: { url: "https://example.invalid/synthetic-article" }, halted: false,
    chrome: { tabs: { update: async (id, params) => { calls.push({ id, url: params.url }); } } },
    gateWatch: () => ({ promise: null, stop() {} }),
    within: async (promise) => await promise,
    waitNavigated: async () => {
      if (++movementChecks === 1) throw new Error("Synthetic wait failure AFTER update accepted");
    },
    waitComplete: async () => {},
    setTimeout: (callback, delay) => { waits.push(delay); callback(); },
  });
  await new vm.Script(`(async () => { ${block}\n })()`).runInContext(context, { timeout: 1000 });
  const result = {
    version: "0.14.31", real_browser_actions: 0,
    worker_sha256: crypto.createHash("sha256").update(source).digest("hex"),
    accepted_tabs_update_count_after_one_wait_failure: calls.length,
    internal_retry_delay_ms: waits,
    conclusion: "A failed wait after an accepted navigation triggers another tabs.update",
  };
  const output = path.join(process.env.SCHOLAR_SEARCH_HOME, "verification/2026-11-26-codex-0.14.31/navigation-replay.json");
  fs.writeFileSync(output, JSON.stringify(result, null, 2), "utf8");
  process.stdout.write(JSON.stringify(result, null, 2) + "\n");
}
main().catch((error) => { process.stderr.write(String(error.stack) + "\n"); process.exitCode = 1; });
