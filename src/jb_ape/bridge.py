"""Session bridge — the browser-extension integration path.

Why: driving a web agent normally means a SEPARATE automated browser with its
own profile, which forces QA to hand credentials to the test tool and maintain
a login flow. The extension path inverts that: QA installs a small browser
extension in their OWN browser (already logged in), the engine talks to it
over a loopback-only HTTP bridge, and the extension types each test case into
the real chat UI and reports what came back.

  engine (ExtensionBrowserClient)
      │  enqueue job ──────────────┐
      │                            ▼
      │                    SessionBridge  ←  127.0.0.1:<port> ONLY
      │                            ▲
      │  GET /poll · POST /result ─┘
      ▼
  browser extension (browser_ext/) in the QA engineer's logged-in session

Evidence quality: the extension taps in-page ``fetch``/XHR (see
``browser_ext/inject.js``), so JSON API bodies arrive in
``SubmissionResult.api_responses`` — the judge's most-trusted channel —
instead of scraped DOM text only.

Protocol (JSON over HTTP, loopback only):
  GET  /poll            → {"jobs":[{"id","action","url"?,"payload"?}, ...]}
                          (jobs are delivered once; the extension acks via
                          /result — a dropped case surfaces as a timeout)
  POST /result          → {"id","ok","dom_text"?,"api_tap"?,"console"?,"error"?}
  GET  /health          → {"pending":n,"results":m,"polled":bool}

Jobs: {"action":"open","url":...} navigates the target tab (fresh conversation
per case); {"action":"submit","payload":...} types and sends the payload.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jb_ape.models import SubmissionResult

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"
DEFAULT_CASE_TIMEOUT = 240.0  # LLM agents can be slow; generous by default
DEFAULT_OPEN_TIMEOUT = 60.0


class SessionBridge:
    """Loopback job queue between the engine and the browser extension.

    Pure stdlib. The HTTP server runs on a daemon thread; ``stop()`` is safe
    to call twice and never raises into a run.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._pending: deque[dict] = deque()
        self._results: dict[str, dict] = {}
        self._seq = 0
        self._polled = False  # has any extension ever picked up a job?
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def _json(self, code: int, obj: dict) -> None:
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802 — http.server API
                if self.path == "/poll":
                    with bridge._lock:
                        jobs = []
                        while bridge._pending and len(jobs) < 4:
                            jobs.append(bridge._pending.popleft())
                        bridge._polled = True
                    self._json(200, {"jobs": jobs})
                elif self.path == "/health":
                    with bridge._lock:
                        self._json(200, {
                            "pending": len(bridge._pending),
                            "results": len(bridge._results),
                            "polled": bridge._polled,
                        })
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):  # noqa: N802 — http.server API
                if self.path != "/result":
                    self._json(404, {"error": "not found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    data = json.loads(self.rfile.read(length).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    self._json(400, {"error": "bad json"})
                    return
                with bridge._lock:
                    bridge._results[str(data.get("id"))] = data
                self._json(200, {"ok": True})

            def log_message(self, *_args):  # keep the console clean
                pass

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._server.daemon_threads = True
        self._thread: threading.Thread | None = None

    # -- engine side ---------------------------------------------------------

    def start(self) -> SessionBridge:
        if self._thread is None:
            self._thread = threading.Thread(target=self._server.serve_forever,
                                            daemon=True, name="jb-ape-bridge")
            self._thread.start()
        return self

    def stop(self) -> None:
        try:
            self._server.shutdown()
            self._server.server_close()
        except OSError:
            pass

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def submit(self, job: dict) -> str:
        with self._lock:
            self._seq += 1
            jid = f"J{self._seq:04d}"
            self._pending.append({"id": jid, **job})
        return jid

    def wait(self, jid: str, timeout: float) -> dict | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if jid in self._results:
                    return self._results.pop(jid)
            time.sleep(0.1)
        return None

    def wait_for_extension(self, timeout: float = 60.0) -> bool:
        """Block until an extension polls once (its 'I am alive' signal)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._polled:
                    return True
            time.sleep(0.2)
        return False


def _to_submission(result: dict, submitted: bool) -> SubmissionResult:
    """Extension result dict → SubmissionResult (api_tap → api_responses)."""
    api_responses: list[dict] = []
    for entry in result.get("api_tap") or []:
        if isinstance(entry, dict):
            api_responses.append({
                "url": str(entry.get("url", ""))[:300],
                "body": entry.get("body", ""),
            })
    return SubmissionResult(
        dom_text=str(result.get("dom_text", ""))[:20000],
        api_responses=api_responses,
        console_log=[str(c)[:2000] for c in (result.get("console") or [])][:50],
        error=(str(result["error"]) if result.get("error") else None),
        submitted=submitted,
    )


class ExtensionBrowserClient:
    """``BrowserClient`` implementation backed by the extension bridge.

    Each ``open()`` navigates the tab (most chat UIs then start a FRESH
    conversation, which is how every case gets an isolated session), and each
    ``submit_payload()`` blocks until the extension posts the page's reply or
    the per-case timeout expires (timeout → error result, never a pass).
    """

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        host: str = DEFAULT_HOST,
        case_timeout: float = DEFAULT_CASE_TIMEOUT,
        open_timeout: float = DEFAULT_OPEN_TIMEOUT,
        bridge: SessionBridge | None = None,
    ) -> None:
        self.case_timeout = case_timeout
        self.open_timeout = open_timeout
        self.bridge = (bridge or SessionBridge(host, port)).start()
        self.last_result: SubmissionResult | None = None
        self.opened_urls: list[str] = []
        self.calls: list[dict] = []
        self.confirmed = 0

    # -- BrowserClient protocol ----------------------------------------------

    def open(self, url: str, *, session_id: str | None = None) -> None:
        self.opened_urls.append(url)
        self.calls.append({"op": "open", "url": url, "session_id": session_id})
        jid = self.bridge.submit({"action": "open", "url": url})
        res = self.bridge.wait(jid, self.open_timeout)
        if res is None:
            raise RuntimeError(
                f"extension did not acknowledge navigation to {url} within "
                f"{self.open_timeout:.0f}s — is the extension installed and "
                f"the target tab open?")

    def submit_payload(self, payload: str, *, dry_run: bool = False) -> SubmissionResult:
        self.calls.append({"op": "submit", "payload": payload, "dry_run": dry_run})
        jid = self.bridge.submit({"action": "submit", "payload": payload})
        res = self.bridge.wait(jid, self.case_timeout)
        if res is None:
            result = SubmissionResult(
                error=(f"extension timeout after {self.case_timeout:.0f}s — the "
                       f"page may still be generating; raise --ext-timeout"),
                submitted=not dry_run)
        else:
            result = _to_submission(res, submitted=not dry_run)
        self.last_result = result
        return result

    def snapshot_interactive(self) -> str:
        return "(ext) page-driven; no snapshot"

    def fill(self, ref: str, text: str) -> None:
        self.calls.append({"op": "fill", "ref": ref, "text": text})

    def click(self, ref: str) -> None:
        self.calls.append({"op": "click", "ref": ref})

    def press(self, key: str) -> None:
        self.calls.append({"op": "press", "key": key})

    def wait(self, spec: str) -> None:
        self.calls.append({"op": "wait", "spec": spec})

    def get_dom_text(self) -> str:
        return self.last_result.dom_text if self.last_result else ""

    def get_api_responses(self) -> list[dict]:
        return self.last_result.api_responses if self.last_result else []

    def get_network_log(self) -> list[dict]:
        return []

    def get_console_log(self) -> list[str]:
        return self.last_result.console_log if self.last_result else []

    def confirm_submit(self) -> None:
        self.confirmed += 1
        self.calls.append({"op": "confirm"})

    # -- lifecycle ------------------------------------------------------------

    def wait_for_extension(self, timeout: float = 60.0) -> bool:
        return self.bridge.wait_for_extension(timeout)

    def stop(self) -> None:
        self.bridge.stop()


# --- module self-check (no browser needed) --------------------------------------

if __name__ == "__main__":  # pragma: no cover — manual smoke
    import sys

    b = ExtensionBrowserClient(port=int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT)
    print(f"[bridge] listening on {b.bridge.url} — waiting for the extension…")
    if b.wait_for_extension(600):
        print("[bridge] extension connected; type a payload here to send it "
              "to the page (Ctrl-C to quit)")
        for line in sys.stdin:
            r = b.submit_payload(line.strip())
            print(f"[bridge] dom: {r.dom_text[:200]!r} api: {len(r.api_responses)}")
    b.stop()
