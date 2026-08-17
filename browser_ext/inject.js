// inject.js — runs in the MAIN world (page context).
// Taps window.fetch / XMLHttpRequest so the engine can see the JSON API
// bodies behind the chat UI (the judge's most-trusted evidence channel).
// Entries are forwarded to the isolated content script via window.postMessage.
(() => {
  if (window.__JB_APE_TAP_INSTALLED__) return;
  window.__JB_APE_TAP_INSTALLED__ = true;
  const MAX_BODY = 20000;

  const send = (entry) => {
    try {
      window.postMessage({ source: "jb-ape-tap", entry }, "*");
    } catch (_) { /* page CSP oddities must never break the tap */ }
  };

  const snippet = (data) => {
    try {
      if (typeof data === "string") return data.slice(0, MAX_BODY);
      return JSON.stringify(data).slice(0, MAX_BODY);
    } catch (_) { return ""; }
  };

  const interesting = (url) =>
    typeof url === "string" && !url.startsWith("http://127.0.0.1");

  const origFetch = window.fetch;
  if (origFetch) {
    window.fetch = async (...args) => {
      const res = await origFetch(...args);
      try {
        const url = typeof args[0] === "string" ? args[0] : (args[0] && args[0].url) || "";
        if (interesting(url)) {
          const clone = res.clone();
          clone.text().then((body) => send({ url, body: body.slice(0, MAX_BODY) }))
            .catch(() => {});
        }
      } catch (_) { /* never break the page */ }
      return res;
    };
  }

  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__jb_url = url;
    return origOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (payload) {
    if (interesting(this.__jb_url)) {
      this.addEventListener("load", () => {
        try {
          const body = this.responseType === "" || this.responseType === "text"
            ? String(this.responseText || "")
            : snippet(this.response);
          send({ url: String(this.__jb_url || ""), body: body.slice(0, MAX_BODY) });
        } catch (_) { /* ignore */ }
      });
    }
    return origSend.call(this, payload);
  };
})();
