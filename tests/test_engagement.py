"""Tests for the integration architecture: stateful Engagement + MCP logic
(devdocs/17). Proves: stepwise lifecycle, snapshot/resume across "restarts",
observable steer semantics, verdict protocol, MCP logic without fastmcp."""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from jb_ape.catalog import SCENARIOS
from jb_ape.engagement import Engagement, EngagementSpec, create_engagement, get_engagement
from jb_ape.targets import LLMTargetClient


def _fake_target(reply_fn):
    return LLMTargetClient(model="fake", transport=reply_fn)


def _spec(**kw):
    base = {"url": "https://t/", "scenario": "data-exfil", "adapter": "dryrun",
            "planner_kind": "tree", "armory_root": None, "budget": 12,
            "max_rounds": 6, "recon_budget": 0}
    base.update(kw)
    return EngagementSpec(**base)


def _attach(eng, target):
    eng.browser = target
    eng.generator.browser = target


class TestEngagementLifecycle(unittest.TestCase):
    def test_step_advances_and_reports_verdict(self):
        calls = {"n": 0}

        def transport(msgs):
            calls["n"] += 1
            return f"attempt {calls['n']}: nothing leaked"

        eng = create_engagement(_spec())
        _attach(eng, _fake_target(transport))
        s1 = eng.step(rounds=1)
        self.assertGreaterEqual(s1["rounds"], 1)
        self.assertGreaterEqual(s1["submissions"], 1)
        self.assertFalse(s1["achieved"])
        for key in ("id", "achieved", "level", "score", "evidence",
                    "submissions", "budget", "finished"):
            self.assertIn(key, s1)

    def test_win_via_canary(self):
        def transport(msgs):
            last = msgs[-1]["content"]
            i = last.find("RT-")
            return f"ok, transmitting {last[i:i + 11]}" if i >= 0 else "no"

        eng = create_engagement(_spec())
        _attach(eng, _fake_target(transport))
        status = eng.step(rounds=5)
        self.assertTrue(status["achieved"])
        self.assertEqual(status["level"], "S")
        self.assertTrue(status["finished"])
        self.assertIn("RT-", status["evidence"])


class TestSnapshotResume(unittest.TestCase):
    """State must survive a process restart (MCP server resilience)."""

    def test_resume_after_restart(self):
        store = Path(".test-tmp/eng")
        if store.exists():
            shutil.rmtree(store, ignore_errors=True)
        eng = create_engagement(_spec(budget=15, max_rounds=8))
        _attach(eng, _fake_target(lambda m: "I can't do that."))
        s1 = eng.step(rounds=1)
        fp = eng.save(store)
        snap = json.loads(fp.read_text())
        self.assertGreaterEqual(snap["ctx"]["rounds_done"], 1)

        canary = snap["spec"]["canary"]
        self.assertTrue(canary)
        winning = _fake_target(lambda m: f"fine: leaked {canary}")
        eng2 = Engagement.from_snapshot(snap, browser=winning)
        s2 = eng2.step(rounds=4)
        self.assertTrue(s2["achieved"], s2)
        self.assertGreaterEqual(s2["rounds"], s1["rounds"])
        self.assertGreaterEqual(s2["submissions"], s1["submissions"])


class TestSteer(unittest.TestCase):
    def test_steer_rides_on_subsequent_cases(self):
        eng = create_engagement(_spec(budget=9, max_rounds=3))
        _attach(eng, _fake_target(lambda m: "no"))
        eng.step(rounds=1)
        n_before = len(eng.ctx.records)
        before = [r.variant.payload for r in eng.ctx.records]
        self.assertTrue(all("[operator context]" not in p for p in before))
        eng.steer("try base64 encoding of the key")
        eng.step(rounds=1)
        after = [r.variant.payload for r in eng.ctx.records[n_before:]]
        self.assertTrue(after)
        self.assertTrue(any("[operator context] try base64" in p for p in after),
                        "steer hint not observable on subsequent cases")


class TestMcpLogicLayer(unittest.TestCase):
    """MCP tool logic as plain functions — no fastmcp required."""

    def test_list_scenarios_shape(self):
        from jb_ape.mcp_server import mcp_list_scenarios

        rows = mcp_list_scenarios()
        self.assertEqual(len(rows), len(SCENARIOS))
        self.assertTrue(all("sid" in r and "problem" in r for r in rows))

    def test_start_step_status_stop_roundtrip(self):
        from jb_ape import engagement as E
        from jb_ape.mcp_server import (
            mcp_start_engagement,
            mcp_status_engagement,
            mcp_step_engagement,
            mcp_stop_engagement,
        )

        E.REGISTRY.clear()
        E.DEFAULT_STORE.mkdir(parents=True, exist_ok=True)
        s = mcp_start_engagement("https://t/", scenario="sysprompt-leak",
                                 adapter="dryrun", budget=8, max_rounds=4)
        eid = s["id"]
        s2 = mcp_step_engagement(eid, rounds=1)
        self.assertGreaterEqual(s2["submissions"], 1)
        s3 = mcp_status_engagement(eid)
        self.assertEqual(s3["id"], eid)
        s4 = mcp_stop_engagement(eid)
        self.assertTrue(s4["finished"])

    def test_get_engagement_resumes_from_disk(self):
        from jb_ape import engagement as E

        E.REGISTRY.clear()
        eng = create_engagement(_spec(budget=8, max_rounds=3))
        _attach(eng, _fake_target(lambda m: "no"))
        eng.step(rounds=1)
        eng.save()
        eid = eng.id
        E.REGISTRY.pop(eid)  # simulate server restart
        eng2 = get_engagement(eid)  # disk fallback
        self.assertEqual(eng2.id, eid)
        self.assertGreaterEqual(eng2.ctx.rounds_done, 1)


class TestCliEngage(unittest.TestCase):
    def test_engage_start(self):
        from jb_ape.cli import main

        self.assertEqual(main(["engage", "start", "--url", "https://t/",
                               "--scenario", "data-exfil",
                               "--adapter", "dryrun"]), 0)


if __name__ == "__main__":
    unittest.main()
