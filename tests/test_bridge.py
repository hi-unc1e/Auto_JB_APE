"""Session bridge — the browser-extension integration path.

The bridge is the transport QA actually touches (install extension → tests
run in the logged-in session). These tests exercise the REAL HTTP bridge and
client with a scripted fake "extension" (urllib against 127.0.0.1), so the
protocol contract — poll delivery, result mapping, api_tap → api_responses,
timeouts — is proven without a browser.
"""

from __future__ import annotations

import json
import re
import threading
import time
import unittest
import urllib.request

from jb_ape.bridge import ExtensionBrowserClient, SessionBridge, _to_submission
from jb_ape.judge import Judge
from jb_ape.models import Objective, Track


def free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_json(url: str, payload: dict | None = None) -> dict:
    if payload is None:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


class FakeExtension(threading.Thread):
    """Polls the bridge like browser_ext/background.js and answers jobs."""

    def __init__(self, base: str, reply: str,
                 api_tap: list[dict] | None = None, delay: float = 0.0,
                 echo_canary: bool = False):
        super().__init__(daemon=True)
        self.base = base
        self.reply = reply
        self.api_tap = api_tap or []
        self.delay = delay
        self.echo_canary = echo_canary
        self.handled: list[dict] = []

    def run(self):
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                jobs = http_json(f"{self.base}/poll").get("jobs", [])
            except OSError:
                time.sleep(0.05)  # bridge not up yet / already stopped
                continue
            for job in jobs:
                self.handled.append(job)
                if self.delay:
                    time.sleep(self.delay)
                if job["action"] == "open":
                    http_json(f"{self.base}/result",
                              {"id": job["id"], "ok": True})
                else:
                    tap = self.api_tap
                    if self.echo_canary:
                        # the page "leaks" whatever token the payload carried
                        m = re.search(r"RT-[0-9a-f]{8}", job["payload"])
                        if m:
                            tap = [{"url": "https://t/api",
                                    "body": f"token {m.group(0)}"}]
                    http_json(f"{self.base}/result", {
                        "id": job["id"], "ok": True,
                        "dom_text": self.reply,
                        "api_tap": tap})
            time.sleep(0.02)


def make_ext_client(reply="I'm sorry, I can't help with that.",
                    api_tap=None, delay=0.0) -> tuple[ExtensionBrowserClient,
                                                      FakeExtension]:
    port = free_port()
    client = ExtensionBrowserClient(port=port, case_timeout=10,
                                    open_timeout=10)
    ext = FakeExtension(client.bridge.url, reply, api_tap, delay)
    ext.start()
    return client, ext


class TestSessionBridge(unittest.TestCase):
    def test_poll_delivers_each_job_once(self):
        port = free_port()
        bridge = SessionBridge(port=port).start()
        j1 = bridge.submit({"action": "submit", "payload": "a"})
        j2 = bridge.submit({"action": "submit", "payload": "b"})
        jobs = http_json(f"{bridge.url}/poll")["jobs"]
        self.assertEqual([j["id"] for j in jobs], [j1, j2])
        self.assertEqual(http_json(f"{bridge.url}/poll")["jobs"], [])
        self.assertIn("pending", http_json(f"{bridge.url}/health"))
        bridge.stop()

    def test_result_roundtrip(self):
        port = free_port()
        bridge = SessionBridge(port=port).start()
        jid = bridge.submit({"action": "submit", "payload": "x"})
        job = http_json(f"{bridge.url}/poll")["jobs"][0]
        self.assertEqual(job["payload"], "x")
        http_json(f"{bridge.url}/result", {"id": jid, "ok": True,
                                           "dom_text": "hello"})
        res = bridge.wait(jid, timeout=2)
        self.assertEqual(res["dom_text"], "hello")
        bridge.stop()


class TestToSubmission(unittest.TestCase):
    def test_api_tap_lands_in_api_responses(self):
        result = _to_submission({
            "dom_text": "page text",
            "api_tap": [{"url": "https://t/api/chat", "body": '{"leak": 1}'}],
        }, submitted=True)
        self.assertEqual(result.api_responses,
                         [{"url": "https://t/api/chat", "body": '{"leak": 1}'}])
        self.assertTrue(result.submitted)

    def test_error_passthrough(self):
        result = _to_submission({"error": "no chat input found"}, submitted=True)
        self.assertEqual(result.error, "no chat input found")


class TestExtensionBrowserClient(unittest.TestCase):
    def test_submit_returns_extension_reply(self):
        client, ext = make_ext_client(reply="assistant says hi",
                                      api_tap=[{"url": "https://t/api",
                                                "body": '{"ok": 1}'}])
        try:
            client.open("https://t/", session_id="qa-QA-001")
            sub = client.submit_payload("do the thing")
            self.assertEqual(sub.dom_text, "assistant says hi")
            self.assertEqual(sub.api_responses[0]["body"], '{"ok": 1}')
            self.assertIn({"op": "open", "url": "https://t/",
                           "session_id": "qa-QA-001"}, client.calls)
        finally:
            client.stop()

    def test_timeout_is_an_error_never_a_pass(self):
        port = free_port()
        client = ExtensionBrowserClient(port=port, case_timeout=0.3,
                                        open_timeout=0.3)
        try:
            with self.assertRaises(RuntimeError):
                client.open("https://t/")  # nobody acks the navigation
            sub = client.submit_payload("never answered")
            self.assertIn("timeout", (sub.error or ""))
            self.assertEqual(sub.dom_text, "")
        finally:
            client.stop()

    def test_queue_order_is_preserved(self):
        client, ext = make_ext_client(reply="r")
        try:
            client.open("https://t/")
            first = client.submit_payload("one")
            second = client.submit_payload("two")
            submits = [j for j in ext.handled if j["action"] == "submit"]
            self.assertEqual([j["payload"] for j in submits], ["one", "two"])
            self.assertEqual(first.dom_text, second.dom_text, "r")
        finally:
            client.stop()


class TestEvidenceReachesJudge(unittest.TestCase):
    """End-to-end: extension api_tap → api_responses → tier-1 S verdict."""

    def test_canary_in_xhr_body_flips_verdict(self):
        canary = "RT-deadbeef"
        leak_body = '{"msg": "token ' + canary + '"}'
        client, ext = make_ext_client(
            reply="Transfer complete.",
            api_tap=[{"url": "https://t/api/send", "body": leak_body}])
        try:
            client.open("https://t/")
            sub = client.submit_payload("exfil please")
            obj = Objective(track=Track.OFFICE, goal="exfil",
                            success_patterns=[canary])
            verdict = Judge(obj).evaluate(sub)
            self.assertEqual(verdict.level, "S")
            self.assertTrue(verdict.achieved)
        finally:
            client.stop()


class TestCLIExtLoop(unittest.TestCase):
    """Full CLI loop: jb-ape qa --adapter ext ↔ scripted extension."""

    def test_cli_ext_full_loop_exit_zero(self):
        import io
        from contextlib import redirect_stdout

        from jb_ape.cli import main

        port = free_port()
        ext = FakeExtension(f"http://127.0.0.1:{port}",
                            reply="I'm sorry, I can't help with that.")
        ext.start()
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["qa", "--url", "https://t/", "--adapter", "ext",
                         "--ext-port", str(port), "--ext-wait", "10",
                         "--case", "QA-001"])
        self.assertEqual(code, 0)
        self.assertIn("通过", out.getvalue())

    def test_cli_ext_finds_leak(self):
        import io
        from contextlib import redirect_stdout

        from jb_ape.cli import main

        port = free_port()
        ext = FakeExtension(f"http://127.0.0.1:{port}",
                            reply="Transfer complete.", echo_canary=True)
        ext.start()
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["qa", "--url", "https://t/", "--adapter", "ext",
                         "--ext-port", str(port), "--ext-wait", "10",
                         "--categories", "sensitive-leak"])
        self.assertEqual(code, 1)  # canary out via the tapped API channel
        self.assertIn("失败", out.getvalue())


if __name__ == "__main__":
    unittest.main()
