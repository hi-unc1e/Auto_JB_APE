"""Tests for the browser contract + LLM fakes (devdocs/08)."""

from __future__ import annotations

import unittest

from jb_ape.browser import DryRunBrowserClient, agent_browser_cheatsheet
from jb_ape.llm import EchoLLM, ScriptedLLM
from jb_ape.models import SubmissionResult


class TestDryRunBrowserClient(unittest.TestCase):
    def test_records_open(self):
        c = DryRunBrowserClient()
        c.open("https://x/", session_id="s1")
        self.assertEqual(c.opened_urls, ["https://x/"])
        self.assertEqual(c.calls[0]["session_id"], "s1")

    def test_submit_returns_queued_response(self):
        c = DryRunBrowserClient(responses=[SubmissionResult(dom_text="hello")])
        r = c.submit_payload("payload", dry_run=True)
        self.assertEqual(r.dom_text, "hello")
        # dry_run=True → submitted flag is False.
        self.assertFalse(r.submitted)

    def test_submit_default_response(self):
        c = DryRunBrowserClient()
        r = c.submit_payload("payload")
        self.assertIn("dry-run", r.dom_text)

    def test_confirm_submit_counted(self):
        c = DryRunBrowserClient()
        c.confirm_submit()
        c.confirm_submit()
        self.assertEqual(c.confirmed, 2)

    def test_fill_click_recorded(self):
        c = DryRunBrowserClient()
        c.fill("@e1", "text")
        c.click("@e2")
        self.assertEqual(c.fills, [("@e1", "text")])
        self.assertEqual(c.clicks, ["@e2"])

    def test_snapshot_returns_text(self):
        c = DryRunBrowserClient()
        snap = c.snapshot_interactive()
        self.assertIn("@e1", snap)


class TestCheatsheet(unittest.TestCase):
    def test_returns_json(self):
        import json

        data = json.loads(agent_browser_cheatsheet())
        self.assertIn("open", data)
        self.assertIn("snapshot", data)


class TestEchoLLM(unittest.TestCase):
    def test_echoes_user_when_no_canned(self):
        llm = EchoLLM()
        self.assertEqual(llm.chat("sys", "hello"), "hello")
        self.assertEqual(len(llm.calls), 1)

    def test_returns_canned(self):
        llm = EchoLLM(canned="canned")
        self.assertEqual(llm.chat("sys", "user"), "canned")


class TestScriptedLLM(unittest.TestCase):
    def test_returns_in_order(self):
        llm = ScriptedLLM(["a", "b"])
        self.assertEqual(llm.chat("s", "u"), "a")
        self.assertEqual(llm.chat("s", "u"), "b")
        # Exhausted → empty string.
        self.assertEqual(llm.chat("s", "u"), "")


if __name__ == "__main__":
    unittest.main()
