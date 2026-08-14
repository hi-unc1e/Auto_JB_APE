"""Tests for the tool layer: catalog + real adapters + CLI (devdocs/15 fusion).

The acceptance bar for "solves 80% of agent red-team problems": every catalog
scenario must be runnable end-to-end, judged machine-provably via canary or
preset patterns, against a browser OR an API target — proven here with a fake
transport, no network, no real browser.
"""

from __future__ import annotations

import unittest

from jb_ape.catalog import (
    PROBLEM_CATEGORIES,
    SCENARIOS,
    build_objective,
    hijack_markers_for,
    mint_canary,
    scenarios_for_track,
)
from jb_ape.cli import main
from jb_ape.facade import build_engine
from jb_ape.generator import RunConfig
from jb_ape.models import Track
from jb_ape.targets import AgentBrowserClient, LLMTargetClient


class TestCatalogIntegrity(unittest.TestCase):
    def test_covers_all_problem_categories(self):
        got = {s.problem for s in SCENARIOS.values()}
        for cat in PROBLEM_CATEGORIES:
            self.assertIn(cat, got, f"category {cat} uncovered")

    def test_every_scenario_builds_compilable_objective(self):
        for sc in SCENARIOS.values():
            fills = {"goal": "write an exploit"} if "{goal}" in sc.goal_template else None
            obj = build_objective(sc, canary="RT-fixed01" if sc.canary else None,
                                  goal_fills=fills)
            self.assertEqual(obj.track, sc.track)
            self.assertNotIn("{canary}", obj.goal, f"{sc.sid} unsubstituted canary")
            self.assertNotIn("{goal}", obj.goal, f"{sc.sid} unfilled goal slot")
            # every pattern must compile (Objective falls back on bad regex,
            # so prove compile explicitly)
            import re

            for pat in obj.success_patterns:
                re.compile(pat)

    def test_canary_required_for_canary_scenarios(self):
        """Pure-function contract: canary=None on a canary scenario is a bug."""
        with self.assertRaises(ValueError):
            build_objective(SCENARIOS["data-exfil"], canary=None)

    def test_canary_contract(self):
        """Signal contract: canary changes the objective's provability."""
        sc = SCENARIOS["data-exfil"]
        plain = build_objective(SCENARIOS["sysprompt-leak"])
        self.assertNotIn("RT-", plain.goal)
        obj = build_objective(sc, canary="RT-deadbeef")
        self.assertIn("RT-deadbeef", obj.goal)
        self.assertGreater(len(obj.success_patterns), len(sc.success_patterns))
        # the pattern actually matches evidence containing the token...
        self.assertIsNotNone(obj.matches_success_pattern("leaked: RT-deadbeef here"))
        # ...and the plain objective does NOT match the same evidence.
        self.assertIsNone(plain.matches_success_pattern("leaked: RT-deadbeef here"))

    def test_hijack_markers(self):
        sc = SCENARIOS["tool-call-hijack"]
        markers = hijack_markers_for(sc, "RT-abc12345")
        self.assertEqual(markers, ["RT-abc12345"])
        self.assertEqual(hijack_markers_for(SCENARIOS["data-exfil"], "x"), [])

    def test_mint_canary_shape(self):
        c = mint_canary()
        self.assertRegex(c, r"^RT-[0-9a-f]{8}$")
        self.assertNotEqual(c, mint_canary())

    def test_track_filter(self):
        coding = scenarios_for_track(Track.CODING)
        self.assertTrue(coding)
        self.assertTrue(all(s.track == Track.CODING for s in coding))


class TestAgentBrowserClientPure(unittest.TestCase):
    """Command construction is pure — testable without the binary."""

    SNAP = (
        "Page: Target\n@e1 [textarea] placeholder=\"Input\"\n"
        "@e2 [button] \"Submit\"\n@e3 [a] \"Home\""
    )

    def test_find_input_ref(self):
        self.assertEqual(AgentBrowserClient.find_input_ref(self.SNAP), "e1")

    def test_find_submit_ref(self):
        self.assertEqual(AgentBrowserClient.find_submit_ref(self.SNAP), "e2")

    def test_find_refs_fallback(self):
        self.assertEqual(AgentBrowserClient.find_input_ref("nothing"), "@e1")
        self.assertEqual(AgentBrowserClient.find_submit_ref("nothing"), "@e2")

    def test_build_wait_args(self):
        self.assertEqual(AgentBrowserClient.build_wait_args("load networkidle"),
                         ["--load", "networkidle"])
        self.assertEqual(AgentBrowserClient.build_wait_args("url **/dash"),
                         ["--url", "**/dash"])
        self.assertEqual(AgentBrowserClient.build_wait_args("text ok"),
                         ["--text", "ok"])
        self.assertEqual(AgentBrowserClient.build_wait_args("garbage"),
                         ["--load", "networkidle"])

    def test_build_submit_sequence(self):
        seq = AgentBrowserClient.build_submit_sequence("PAYLOAD", self.SNAP)
        self.assertEqual(seq[0], ["fill", "e1", "PAYLOAD"])
        self.assertEqual(seq[1], ["click", "e2"])
        self.assertEqual(seq[2], ["wait", "--load", "networkidle"])


class TestLLMTargetClient(unittest.TestCase):
    def _client(self, reply: str):
        return LLMTargetClient(model="fake", transport=lambda msgs: reply)

    def test_reply_lands_in_api_channel(self):
        c = self._client("hello target")
        r = c.submit_payload("ping")
        self.assertEqual(r.api_responses[0]["content"], "hello target")
        self.assertTrue(r.submitted)
        self.assertEqual(r.error, None)

    def test_history_is_multiturn(self):
        c = self._client("r1")
        c.submit_payload("u1")
        c.submit_payload("u2")
        self.assertEqual(len(c.get_api_responses()), 2)

    def test_transport_error_is_evidence_not_crash(self):
        def boom(msgs):
            raise RuntimeError("down")

        c = LLMTargetClient(model="fake", transport=boom)
        r = c.submit_payload("x")
        self.assertIn("transport error", r.error or "")
        self.assertFalse(r.submitted is True and r.error)

    def test_sessions_isolated(self):
        c = self._client("same-reply")
        c.open("https://a/", session_id="s1")
        c.submit_payload("one")
        c.open("https://b/", session_id="s2")
        c.submit_payload("two")
        # two distinct histories
        self.assertEqual(len(c._histories), 2)


class TestEndToEndViaFakeTransport(unittest.TestCase):
    """Acceptance: a catalog scenario runs the FULL loop and the canary in the
    target's reply machine-proves success."""

    def test_data_exfil_canary_win(self):
        sc = SCENARIOS["data-exfil"]
        canary = "RT-cafe1234"
        obj = build_objective(sc, canary=canary)
        target = LLMTargetClient(model="fake",
                                 transport=lambda msgs: f"ok, sent {canary}")
        gen = build_engine(obj, browser=target, armory_root=None,
                           config=RunConfig(run_recon=False, bundle_size=2,
                                            max_rounds=2))
        rep = gen.run("https://t/", budget=6)
        self.assertTrue(rep.achieved)
        self.assertEqual(rep.confirmed, 1)

    def test_tool_call_hijack_canary_win(self):
        sc = SCENARIOS["tool-call-hijack"]
        canary = "RT-beef5678"
        obj = build_objective(sc, canary=canary)
        markers = hijack_markers_for(sc, canary)
        reply = ('{"name": "run_terminal", "arguments": '
                 '{"command": "echo ' + canary + '"}}')
        target = LLMTargetClient(model="fake", transport=lambda msgs: reply)
        gen = build_engine(obj, browser=target, armory_root=None,
                           hijack_success_markers=markers,
                           config=RunConfig(run_recon=False, bundle_size=2,
                                            max_rounds=2))
        rep = gen.run("https://t/", budget=6)
        self.assertTrue(rep.achieved)
        self.assertEqual(rep.best.level if rep.best else "?", "S")

    def test_refusal_is_not_a_win(self):
        sc = SCENARIOS["data-exfil"]
        obj = build_objective(sc, canary="RT-nope9999")
        target = LLMTargetClient(model="fake",
                                 transport=lambda msgs: "I can't help with that.")
        gen = build_engine(obj, browser=target, armory_root=None,
                           config=RunConfig(run_recon=False, bundle_size=1,
                                            max_rounds=1))
        rep = gen.run("https://t/", budget=3)
        self.assertFalse(rep.achieved)


class TestCLI(unittest.TestCase):
    def test_scenarios_lists_catalog(self):
        self.assertEqual(main(["scenarios"]), 0)

    def test_run_raw_goal_dryrun(self):
        code = main(["run", "--url", "https://t/", "--adapter", "dryrun",
                     "--armory", "armory", "--no-recon",
                     "--track", "office", "--goal", "test goal"])
        self.assertEqual(code, 0)

    def test_run_strict_fails_when_not_achieved(self):
        code = main(["run", "--url", "https://t/", "--adapter", "dryrun",
                     "--armory", "armory", "--no-recon",
                     "--scenario", "sysprompt-leak", "--strict"])
        self.assertEqual(code, 1)

    def test_sweep_dryrun(self):
        code = main(["sweep", "--url", "https://t/", "--adapter", "dryrun",
                     "--armory", "armory", "--track", "office",
                     "--each-budget", "2"])
        self.assertEqual(code, 0)

    def test_unknown_adapter_exits(self):
        with self.assertRaises(SystemExit):
            main(["recon", "--url", "https://t/", "--adapter", "nope"])

    def test_llm_adapter_requires_model(self):
        with self.assertRaises(SystemExit):
            main(["run", "--url", "https://t/", "--adapter", "llm",
                  "--scenario", "data-exfil"])


if __name__ == "__main__":
    unittest.main()
