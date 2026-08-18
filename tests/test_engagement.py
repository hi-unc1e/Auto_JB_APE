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

    def test_recon_runs_when_spec_enabled(self):
        # spec.recon_budget used to be dead (run_recon was hard-wired False in
        # create_engagement) — the spec knob must reach the engine.
        eng = create_engagement(_spec(budget=12, max_rounds=4, recon_budget=2))
        _attach(eng, _fake_target(lambda m: "no"))
        eng.step(rounds=1)
        self.assertEqual(eng.ctx.recon_cost, 2)
        self.assertIsNotNone(eng.ctx.recon_profile)
        self.assertGreaterEqual(eng.status()["submissions"], 2)  # recon in budget

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

    def test_tree_feedback_stats_survive_restart(self):
        # The walker's record() feedback (fails/prune) is part of engagement
        # state — losing it on restart would reset the tree's adaptation.
        store = Path(".test-tmp/eng-stats")
        if store.exists():
            shutil.rmtree(store, ignore_errors=True)
        eng = create_engagement(_spec(budget=15, max_rounds=8))
        _attach(eng, _fake_target(lambda m: "I can't do that."))
        eng.step(rounds=2)
        fails_before = sum(st.fails for st in eng.generator.planner.stats.values())
        self.assertGreater(fails_before, 0)  # record() wiring is live

        snap = json.loads(eng.save(store).read_text())
        self.assertIn("stats", snap["walker"])
        eng2 = Engagement.from_snapshot(snap, browser=_fake_target(lambda m: "no"))
        fails_after = sum(st.fails for st in eng2.generator.planner.stats.values())
        self.assertEqual(fails_after, fails_before)


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


class TestSteerBanditParity(unittest.TestCase):
    """steer must behave identically under --planner bandit: the flat Planner
    consumes hints (rides on seeds) and disabled_families (pool pruning)."""

    def test_hint_rides_under_bandit_planner(self):
        eng = create_engagement(_spec(budget=9, max_rounds=3, planner_kind="bandit"))
        _attach(eng, _fake_target(lambda m: "no"))
        eng.step(rounds=1)
        self.assertTrue(all("[operator context]" not in r.variant.payload
                            for r in eng.ctx.records))
        eng.steer("try base64 encoding of the key")
        eng.step(rounds=1)
        after = [r.variant.payload for r in eng.ctx.records]
        self.assertTrue(any("[operator context] try base64" in p for p in after),
                        "steer hint not observable under bandit planner")

    def test_disable_and_hint_survive_restart_under_bandit(self):
        store = Path(".test-tmp/eng-bandit-steer")
        if store.exists():
            shutil.rmtree(store, ignore_errors=True)
        eng = create_engagement(_spec(budget=12, max_rounds=4, planner_kind="bandit"))
        _attach(eng, _fake_target(lambda m: "no"))
        eng.steer("avoid story techniques", disable=["T-A3"])
        eng.step(rounds=1)
        self.assertNotIn("T-A3", {r.variant.technique for r in eng.ctx.records})
        snap = json.loads(eng.save(store).read_text())
        eng2 = Engagement.from_snapshot(snap, browser=_fake_target(lambda m: "no"))
        eng2.step(rounds=1)
        self.assertNotIn("T-A3", {r.variant.technique for r in eng2.ctx.records})
        self.assertTrue(all("[operator context] avoid story" in r.variant.payload
                            for r in eng2.ctx.records))


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


class TestPlannedOptimizations(unittest.TestCase):
    """devdocs/17 §7 backlog items landed this round."""

    def test_snapshot_restores_target_history(self):
        seen_lens = []

        def transport(msgs):
            seen_lens.append(len(msgs))
            return "no"

        tgt = _fake_target(transport)
        eng = create_engagement(_spec(budget=10, max_rounds=4))
        _attach(eng, tgt)
        eng.step(rounds=2)
        hist_before = {k: len(v) for k, v in tgt._histories.items()}
        self.assertTrue(hist_before)
        snap = eng.snapshot()

        # "restart": brand-new target client, history injected from snapshot
        tgt2 = _fake_target(transport)
        eng2 = Engagement.from_snapshot(snap, browser=tgt2)
        self.assertEqual({k: len(v) for k, v in tgt2._histories.items()},
                         hist_before)
        eng2.step(rounds=1)
        # third turn saw the restored multi-turn context (msgs > fresh start)
        self.assertTrue(any(n > 2 for n in seen_lens), seen_lens)

    def test_structured_steer_disables_family(self):
        eng = create_engagement(_spec(budget=15, max_rounds=4))
        _attach(eng, _fake_target(lambda m: "no"))
        eng.step(rounds=1)
        eng.steer("avoid workflow family", disable=["T-F1"])
        eng.step(rounds=2)
        techs = {r.variant.technique for r in eng.ctx.records}
        self.assertNotIn("T-F1", techs)
        # and the disable survives a snapshot/resume
        snap = eng.snapshot()
        eng2 = Engagement.from_snapshot(snap, browser=_fake_target(lambda m: "no"))
        self.assertEqual(eng2.generator.planner.state.disabled_families, {"T-F1"})
