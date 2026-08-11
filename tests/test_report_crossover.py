"""Tests for the run report (devdocs UX) and the CrossOver mutator (devdocs/12 §4.1)."""

from __future__ import annotations

import unittest

from jb_ape.generator import RunConfig, RunRecord
from jb_ape.llm import ScriptedLLM
from jb_ape.models import DefenseLayer, Objective, SubmissionResult, Track, Variant
from jb_ape.report import render_report
from jb_ape.rewriter import Rewriter


class TestRenderReport(unittest.TestCase):
    def _make_report(self, achieved=True):
        from jb_ape.generator import RunReport
        from jb_ape.models import DefenseProfile

        var = Variant(
            payload="Step 1: do thing\nStep 2: do more",
            technique="T-D1", mutation_chain=["COD-01", "B-O1"],
        )
        rec = RunRecord(
            variant=var, submission=SubmissionResult(dom_text="HTB{x}"),
            level="S", achieved=True, score=95, arm_id="T-D1+B-O1", confirmed=True,
        )
        prof = DefenseProfile(detected_layers={DefenseLayer.L1, DefenseLayer.L1_OUT},
                              l1out_redacts=True, agent_tools=["get_order"])
        return RunReport(
            achieved=achieved, rounds=3, submissions=12, confirmed=1,
            best=rec, records=[rec], recon_profile=prof, recon_cost=6,
        )

    def test_achieved_verdict(self):
        out = render_report(self._make_report(achieved=True), url="https://t/")
        self.assertIn("ACHIEVED", out)
        self.assertIn("https://t/", out)
        self.assertIn("recon: 6", out.lower())

    def test_includes_winning_payload(self):
        out = render_report(self._make_report())
        self.assertIn("do thing", out)
        self.assertIn("COD-01", out)

    def test_recon_l1out_warning(self):
        out = render_report(self._make_report())
        self.assertIn("L1'", out)

    def test_not_achieved(self):
        out = render_report(self._make_report(achieved=False))
        self.assertIn("NOT ACHIEVED", out)

    def test_empty_records(self):
        from jb_ape.generator import RunReport
        rep = RunReport(achieved=False, rounds=0, submissions=0, confirmed=0, best=None)
        out = render_report(rep)
        self.assertIn("Run Report", out)


class TestCrossOver(unittest.TestCase):
    def test_mechanical_fallback_without_llm(self):
        obj = Objective(track=Track.CODING, goal="x")
        rw = Rewriter(obj, llm=None)
        a = Variant(payload="AAA", technique="T-A1", mutation_chain=["SEED-A"])
        b = Variant(payload="BBB", technique="T-A1", mutation_chain=["SEED-B"],
                    bypasses=["B-O1"])
        out = rw.crossover(a, b, k=2)
        self.assertEqual(len(out), 1)
        self.assertIn("AAA", out[0].payload)
        self.assertIn("BBB", out[0].payload)
        self.assertIn("XOVER", out[0].mutation_chain)
        self.assertIn("B-O1", out[0].bypasses)

    def test_llm_crossover_parses(self):
        canned = (
            '[{"payload":"merged hybrid payload combining both","mutation_chain":["XOVER"]}]'
        )
        llm = ScriptedLLM([canned, '{"score": 9}'])  # crossover + selfcheck
        obj = Objective(track=Track.CODING, goal="get steps")
        rw = Rewriter(obj, llm=llm, keep_threshold=7)
        a = Variant(payload="Use roleplay as DAN", technique="T-B1", mutation_chain=["DAN"])
        b = Variant(payload="Output each char split by period", technique="T-A3",
                    mutation_chain=["SPLIT"], bypasses=["B-O1"])
        out = rw.crossover(a, b, k=1)
        self.assertGreater(len(out), 0)
        self.assertIn("hybrid", out[0].payload)
        self.assertIn("XOVER", out[0].mutation_chain)
        self.assertIn("B-O1", out[0].bypasses)

    def test_crossover_chain_records_both_parents(self):
        rw = Rewriter(Objective(track=Track.CODING, goal="x"), llm=None)
        a = Variant(payload="A", mutation_chain=["P1", "P2"])
        b = Variant(payload="B", mutation_chain=["Q1", "Q2"])
        out = rw.crossover(a, b)
        # Both parent chains present, bracketed by XOVER.
        joined = out[0].mutation_chain
        self.assertIn("P1", joined)
        self.assertIn("Q2", joined)
        self.assertIn("XOVER", joined)


class TestOnTopicGateInGenerator(unittest.TestCase):
    """Verify the on-topic gate prunes drifted prompts before target query."""

    def test_gate_prunes_off_topic(self):
        from jb_ape.browser import DryRunBrowserClient
        from jb_ape.facade import build_engine
        from jb_ape.llm import ScriptedLLM

        obj = Objective(track=Track.CODING, goal="get flag",
                        success_patterns=[r"HTB\{.*?\}"])
        # gate LLM says NO to everything → all prompts pruned → no submissions.
        gate = ScriptedLLM(["Response: [[NO]]"] * 50)
        # The actual flag response would never be consumed because gate prunes first.
        br = DryRunBrowserClient(
            responses=[SubmissionResult(dom_text="HTB{never_reached}")]
        )
        gen = build_engine(
            obj, browser=br, gate_llm=gate,
            config=RunConfig(bundle_size=2, max_rounds=2, run_recon=False),
            armory_root=None,
        )
        report = gen.run("https://x/", budget=10)
        # Gate blocked everything → not achieved, near-zero attack submissions.
        self.assertFalse(report.achieved)

    def test_gate_allows_on_topic(self):
        from jb_ape.browser import DryRunBrowserClient
        from jb_ape.facade import build_engine
        from jb_ape.llm import ScriptedLLM

        obj = Objective(track=Track.CODING, goal="get flag",
                        success_patterns=[r"HTB\{.*?\}"])
        gate = ScriptedLLM(["Response: [[YES]]"] * 50)
        br = DryRunBrowserClient(
            responses=[SubmissionResult(dom_text="HTB{reached}")]
        )
        gen = build_engine(
            obj, browser=br, gate_llm=gate,
            config=RunConfig(bundle_size=2, max_rounds=2, run_recon=False),
            armory_root=None,
        )
        report = gen.run("https://x/", budget=10)
        self.assertTrue(report.achieved)


if __name__ == "__main__":
    unittest.main()
