// background.js — MV3 service worker: polls the local jb-ape bridge and
// drives the target tab. Loopback only; nothing leaves the machine.
const BRIDGE = "http://127.0.0.1:8765";
const POLL_MS = 700;
let targetTabId = null;
let busy = false;

async function postResult(payload) {
  try {
    await fetch(BRIDGE + "/result", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (_) { /* bridge down: the engine times out and tells the user */ }
}

async function activeTab() {
  if (targetTabId != null) {
    try {
      const t = await chrome.tabs.get(targetTabId);
      if (t) return t;
    } catch (_) { /* tab closed */ }
  }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  targetTabId = tab ? tab.id : null;
  return tab;
}

async function handleJob(job) {
  if (job.action === "open") {
    let tab = await activeTab();
    if (!tab) tab = await chrome.tabs.create({ url: job.url });
    else await chrome.tabs.update(tab.id, { url: job.url, active: true });
    targetTabId = tab.id;
    // Give the page a moment to start loading; content.js re-injects itself.
    await new Promise((r) => setTimeout(r, 1500));
    await postResult({ id: job.id, ok: true });
    return;
  }
  if (job.action === "submit") {
    const tab = await activeTab();
    if (!tab) return postResult({ id: job.id, ok: false, error: "no target tab" });
    let reply;
    try {
      reply = await chrome.tabs.sendMessage(tab.id, {
        type: "jb-ape-submit", payload: job.payload });
    } catch (e) {
      reply = { ok: false, error: "content script not reachable (refresh the page once): " + e };
    }
    await postResult({ id: job.id, ...reply });
  }
}

async function poll() {
  if (busy) return;
  busy = true;
  try {
    const res = await fetch(BRIDGE + "/poll");
    if (!res.ok) return;
    const { jobs = [] } = await res.json();
    for (const job of jobs) await handleJob(job);
  } catch (_) { /* engine not running — idle */ } finally {
    busy = false;
  }
}

// A continuous fetch cadence keeps the service worker alive during a run.
setInterval(poll, POLL_MS);
poll();
