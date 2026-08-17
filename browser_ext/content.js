// content.js — runs in the ISOLATED world of every page.
// Receives test payloads from the background service worker, types them into
// the page's chat input, sends, waits for the reply to settle, and returns
// {dom_text, api_tap, error} — plus everything the MAIN-world tap posted.
(() => {
  if (window.__JB_APE_CONTENT__) return;
  window.__JB_APE_CONTENT__ = true;

  // --- network tap accumulator (fed by inject.js via postMessage) -----------
  let tap = [];
  window.addEventListener("message", (ev) => {
    if (ev.source === window && ev.data && ev.data.source === "jb-ape-tap") {
      tap.push(ev.data.entry);
      if (tap.length > 200) tap = tap.slice(-200);
    }
  });

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // --- per-site selector overrides (options page) + generic heuristics ------
  async function siteConfig() {
    const host = location.hostname;
    const { jbApeSites = {} } = await chrome.storage.local.get("jbApeSites");
    return jbApeSites[host] || jbApeSites["*"] || {};
  }

  function findInput(cfg) {
    if (cfg.inputSelector) {
      const el = document.querySelector(cfg.inputSelector);
      if (el) return el;
    }
    const candidates = document.querySelectorAll(
      'textarea, div[contenteditable="true"], div[contenteditable="plaintext-only"]');
    let best = null;
    for (const el of candidates) {
      const r = el.getBoundingClientRect();
      if (r.width < 40 || r.height < 12) continue;
      if (!best || r.bottom > best.getBoundingClientRect().bottom) best = el;
    }
    return best;
  }

  function findSendButton(cfg, input) {
    if (cfg.sendSelector) {
      const el = document.querySelector(cfg.sendSelector);
      if (el) return el;
    }
    // Walk up from the input, then look for a clickable sibling/child button.
    const scope = input.closest("form, div[class*='input'], div[class*='composer']") || document;
    const btns = scope.querySelectorAll('button, [role="button"]');
    let best = null;
    for (const b of btns) {
      const label = ((b.getAttribute("aria-label") || "") + " " + b.textContent).toLowerCase();
      if (/send|发送|提交|submit/.test(label)) { best = b; break; }
      if (!best) best = b;
    }
    return best;
  }

  function setNativeValue(el, value) {
    el.focus();
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
      const proto = el instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
      setter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    } else {
      // contenteditable
      el.textContent = value;
      el.dispatchEvent(new InputEvent("input", { bubbles: true, data: value }));
    }
  }

  function pageText() {
    return (document.body?.innerText || "").replace(/\n{3,}/g, "\n\n").trim();
  }

  function replyText(cfg, baseline) {
    if (cfg.replySelector) {
      const nodes = document.querySelectorAll(cfg.replySelector);
      if (nodes.length) return nodes[nodes.length - 1].innerText;
    }
    // Generic: the assistant's reply = whatever the page gained after sending.
    const now = pageText();
    if (now.length > baseline.length) return now.slice(baseline.length).trim();
    return now;
  }

  async function handleSubmit(payload) {
    const cfg = await siteConfig();
    const input = findInput(cfg);
    if (!input) {
      return { ok: false, error: "no chat input found — set selectors on the options page" };
    }
    const baseline = pageText();
    tap = []; // only evidence produced BY this case
    setNativeValue(input, payload);
    await sleep(150);
    const btn = findSendButton(cfg, input);
    if (btn) btn.click();
    else {
      input.dispatchEvent(new KeyboardEvent("keydown",
        { key: "Enter", code: "Enter", bubbles: true }));
    }

    // Wait until the page text stops changing (reply finished) or timeout.
    const deadline = Date.now() + 120000;
    let stable = 0, last = pageText();
    while (Date.now() < deadline) {
      await sleep(500);
      const cur = pageText();
      if (cur === last && cur.length > baseline.length) {
        stable += 1;
        if (stable >= 3) break; // ~1.5s of silence ⇒ reply settled
      } else stable = 0;
      last = cur;
    }
    const domText = replyText(cfg, baseline).slice(0, 20000);
    const apiTap = tap.slice();
    return { ok: true, dom_text: domText, api_tap: apiTap };
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg && msg.type === "jb-ape-submit") {
      tap = [];
      handleSubmit(msg.payload).then(sendResponse).catch((e) =>
        sendResponse({ ok: false, error: String(e) }));
      return true; // async response
    }
  });
})();
