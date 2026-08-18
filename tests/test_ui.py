"""Local web GUI — the zero-cost QA entry point.

Exercises the REAL HTTP server end to end (no browser needed): page serving,
the fixed-suite listing, a full dryrun through the JSON API with streaming
status, the markdown/JSON report endpoints, the concurrent-run mutex, and
error surfacing for a bad configuration.
"""

from __future__ import annotations

import json
import time
import unittest
import urllib.error
import urllib.request

from jb_ape.ui import UIServer


def _get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return r.status, r.read()


def _post(base: str, path: str, obj: dict | None = None):
    req = urllib.request.Request(
        base + path, data=json.dumps(obj or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_finished(base: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, body = _get(base, "/api/status")
        st = json.loads(body)
        if st["status"] in ("finished", "stopped", "error"):
            return st
        time.sleep(0.05)
    raise AssertionError("run did not finish in time")


class TestUIStatic(unittest.TestCase):
    def setUp(self):
        self.srv = UIServer(port=0).start()
        self.base = self.srv.url

    def tearDown(self):
        self.srv.stop()

    def test_page_served(self):
        code, body = _get(self.base, "/")
        self.assertEqual(code, 200)
        self.assertIn("Agent 安全冒烟测试".encode(), body)
        # self-contained: no CDN / external resources
        self.assertNotIn(b"http://cdn", body)
        self.assertNotIn(b"googleapis", body)

    def test_suites_listing_with_payload_preview(self):
        _, body = _get(self.base, "/api/suites")
        cases = json.loads(body)
        self.assertEqual(len(cases), 24)
        self.assertEqual(cases[0]["id"], "QA-001")
        self.assertTrue(all(c["payload"].strip() for c in cases))  # previewable

    def test_env_flags_without_leaking_values(self):
        _, body = _get(self.base, "/api/env")
        env = json.loads(body)
        self.assertEqual(sorted(env), ["openai_base_url_host",
                                       "openai_base_url_set",
                                       "openai_key_set"])
        self.assertIsInstance(env["openai_key_set"], bool)  # booleans only

    def test_check_dryrun_ok(self):
        code, data = _post(self.base, "/api/check", {"adapter": "dryrun"})
        self.assertEqual(code, 200)
        self.assertTrue(data["ok"])
        self.assertIn("离线", data["detail"])

    def test_check_llm_missing_model(self):
        code, data = _post(self.base, "/api/check", {"adapter": "llm"})
        self.assertEqual(code, 200)
        self.assertFalse(data["ok"])
        self.assertIn("模型名", data["detail"])

    def test_check_llm_unreachable_reports_cause(self):
        # no openai package / no network in the hermetic env → ok=False + reason
        code, data = _post(self.base, "/api/check",
                           {"adapter": "llm", "llm_model": "m",
                            "llm_base_url": "http://127.0.0.1:1/v1"})
        self.assertEqual(code, 200)
        self.assertFalse(data["ok"])

    def test_check_ext_no_heartbeat(self):
        code, data = _post(self.base, "/api/check",
                           {"adapter": "ext", "ext_port": _free_port(),
                            "ext_wait": 0.5})
        self.assertEqual(code, 200)
        self.assertFalse(data["ok"])
        self.assertIn("插件", data["detail"])

    def test_unknown_path_404(self):
        code, _ = _post(self.base, "/api/nope", {})
        self.assertEqual(code, 404)


class TestUIRun(unittest.TestCase):
    def setUp(self):
        self.srv = UIServer(port=0).start()
        self.base = self.srv.url

    def tearDown(self):
        self.srv.stop()

    def test_dryrun_full_run_via_api(self):
        code, data = _post(self.base, "/api/run",
                           {"url": "https://t/", "adapter": "dryrun"})
        self.assertEqual(code, 200)
        self.assertEqual(data["total"], 24)
        st = _wait_finished(self.base)
        self.assertEqual(st["status"], "finished")
        self.assertEqual(st["done"], 24)
        self.assertEqual(st["counts"]["pass"], 24)
        self.assertEqual(st["exit_code"], 0)
        self.assertIn("可发布", st["release_advice_zh"])

    def test_demo_run_shows_high_finding(self):
        _post(self.base, "/api/run",
              {"url": "https://t/", "adapter": "dryrun", "demo": True})
        st = _wait_finished(self.base)
        self.assertEqual(st["counts"]["fail_high"], 1)
        self.assertEqual(st["exit_code"], 1)
        finding = next(r for r in st["results"] if r["verdict"] == "fail")
        self.assertEqual(finding["severity"], "high")
        self.assertTrue(finding["fix_zh"])  # plain-language fix present
        self.assertTrue(finding["risk_plain_zh"])

    def test_category_filter_and_report_endpoints(self):
        _post(self.base, "/api/run",
              {"url": "https://t/", "adapter": "dryrun",
               "categories": ["tool-misuse"], "lang": "en"})
        st = _wait_finished(self.base)
        self.assertEqual(st["total"], 2)
        code, body = _get(self.base, "/api/report?format=md&lang=en")
        self.assertEqual(code, 200)
        self.assertIn(b"One-page conclusion", body)
        _, body = _get(self.base, "/api/report?format=json")
        data = json.loads(body)
        self.assertEqual(len(data["results"]), 2)

    def test_concurrent_run_rejected(self):
        _post(self.base, "/api/run",
              {"url": "https://t/", "adapter": "ext", "ext_wait": 15})
        code, data = _post(self.base, "/api/run", {"adapter": "dryrun"})
        self.assertEqual(code, 409)
        self.srv.run.stop_flag.set()

    def test_llm_without_model_is_a_clean_error(self):
        code, data = _post(self.base, "/api/run",
                           {"url": "https://t/", "adapter": "llm"})
        self.assertEqual(code, 200)  # run accepted; fails fast with guidance
        st = _wait_finished(self.base)
        self.assertEqual(st["status"], "error")
        self.assertIn("模型名", st["error"])

    def test_bad_json_body(self):
        req = urllib.request.Request(
            self.base + "/api/run", data=b"{not json",
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("expected 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)


class TestRunStreamingCallback(unittest.TestCase):
    """run_qa(on_result=…) / stop_check=… — the hooks the GUI streams through."""

    def test_on_result_fires_per_case_in_order(self):
        from jb_ape.browser import DryRunBrowserClient
        from jb_ape.qa import build_qa_suite, run_qa

        seen: list[str] = []
        cases = build_qa_suite(categories=["tool-misuse"])
        rep = run_qa("https://t/", DryRunBrowserClient(), cases,
                     on_result=lambda r: seen.append(r.case.id))
        self.assertEqual(seen, [c.id for c in cases])
        self.assertEqual(len(rep.results), len(cases))

    def test_stop_check_yields_partial_report(self):
        from jb_ape.browser import DryRunBrowserClient
        from jb_ape.qa import build_qa_suite, run_qa

        cases = build_qa_suite()  # 24 cases
        holder: dict = {"n": []}
        rep = run_qa("https://t/", DryRunBrowserClient(), cases,
                     stop_check=lambda: len(holder["n"]) >= 3,
                     on_result=lambda r: holder["n"].append(r))
        self.assertEqual(len(rep.results), 3)  # stopped after the 3rd case


if __name__ == "__main__":
    unittest.main()
