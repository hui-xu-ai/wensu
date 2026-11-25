// Readiness and walking for publisher pages (ADR 0026, amendment).
//
// Publisher pages used to have no content script at all, so everything the kernel could do there
// was `goto` + `sleep` — a guess at how long a Nuxt/React page needs. A cold cache proved the guess
// wrong: six seconds produced a skeleton (`status: no_html`) while a warm cache produced the full
// article. This script gives the browser's own view of "the article is here" (instead of a stopwatch)
// and walks the page once so lazy images are actually downloaded before the capture.
//
// It does two things and nothing else: report readiness, and scroll. It reads no data, clicks
// nothing, and never navigates.

(() => {
  if (window.__wensuReadinessInstalled) return;
  window.__wensuReadinessInstalled = true;

  const BODY_HINT = "article, section[id], [class*='article-body'], [class*='articleBody'], main";
  const TEXT_FLOOR = 1500;
  const SETTLE_STEP_MS = 350;
  const SETTLE_LIMIT_MS = 12_000;

  const bodyScore = () => {
    const hinted = document.querySelectorAll(BODY_HINT).length;
    const text = (document.body && document.body.innerText) || "";
    return { hinted, text: text.trim().length };
  };

  const ready = () => {
    const score = bodyScore();
    // A skeleton has markup but almost no text; a paywall has text but no article sections.
    return score.hinted >= 1 && score.text >= TEXT_FLOOR;
  };

  const waitUntilReady = async () => {
    const deadline = Date.now() + SETTLE_LIMIT_MS;
    while (Date.now() < deadline) {
      if (ready()) return true;
      await new Promise((resolve) => setTimeout(resolve, SETTLE_STEP_MS));
    }
    return ready();
  };

  // Walking is what makes `loading="lazy"` images be fetched: the site's own observer sees the
  // viewport move. Steps are viewport-sized so a long article is covered without a huge jump.
  const walk = async () => {
    const step = Math.max(320, Math.floor(window.innerHeight * 0.9));
    const limit = Math.max(document.body.scrollHeight, step);
    for (let y = 0; y < limit; y += step) {
      window.scrollTo(0, y);
      await new Promise((resolve) => setTimeout(resolve, 220));
    }
    window.scrollTo(0, document.documentElement.scrollHeight);
    await new Promise((resolve) => setTimeout(resolve, 400));
    window.scrollTo(0, 0);
    return true;
  };

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    const cmd = message && message.cmd;
    if (cmd === "wensu.ready") {
      sendResponse({ ok: true, ready: ready(), score: bodyScore() });
      return false;
    }
    if (cmd === "wensu.settle") {
      waitUntilReady()
        .then((settled) => sendResponse({ ok: true, ready: settled, score: bodyScore() }))
        .catch(() => sendResponse({ ok: false }));
      return true;
    }
    if (cmd === "wensu.walk") {
      waitUntilReady()
        .then(() => walk())
        .then(() => sendResponse({ ok: true, ready: ready(), score: bodyScore() }))
        .catch(() => sendResponse({ ok: false }));
      return true;
    }
    return false;
  });
})();
