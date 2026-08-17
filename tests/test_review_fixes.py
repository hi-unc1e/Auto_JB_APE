"""Tests for fixes from the multi-reviewer audit (pi P0/P1/P2).

Guards the specific regressions the reviewers caught:
- P0-1: bandit arm id must match planner's sampling space (learning loop alive)
- P1-2: decode reaches the LLM judge (office exfil with no success pattern)
- P1-3: seed placeholders are filled, never shipped literal {callback}
- P2-2: recon never exceeds the run budget
- P0-2/P1-5: judge's resistance_hit reaches the rewriter via real diagnosis
"""

from __future__ import annotations

import unittest
from pathlib import Path

from jb_ape.armory import Armory
from jb_ape.generator import RunRecord, _arm_id, _feedback_for
from jb_ape.llm import ScriptedLLM
from jb_ape.models import (
    DefenseLayer,
    Objective,
    SubmissionResult,
    Track,
    Variant,
)
from jb_ape.planner import TreeNode

FIXTURE_ARMORY = str(Path(__file__).resolve().parent / "fixtures" / "armory")


class TestBanditArmAlignment(unittest.TestCase):
    """P0-1: the bandit must reward the SAME id space it samples on.
    Planner samples bare technique ids; _arm_id must return bare technique."""

    def test_arm_id_is_bare_technique(self):
        v = Variant(payload="x", technique="T-A1", bypasses=["B-I3", "B-O1"])
        self.assertEqual(_arm_id(v), "T-A1")

    def test_arm_id_no_bypass_suffix(self):
        v = Variant(payload="x", technique="T-D3", bypasses=["B-O1"])
        # Must NOT include the bypass — that's the bug.
        self.assertNotIn("B-O1", _arm_id(v))

    def test_rewarded_technique_is_subsequently_selected(self):
        """End-to-end: rewarding a technique biases the planner toward it."""
        from jb_ape.planner import Bandit, Planner

        obj = Objective(track=Track.CODING, goal="x")
        bandit = Bandit()
        planner = Planner(objective=obj, bandit=bandit)
        # Reward T-A1 heavily via the SAME id _arm_id produces.
        for _ in range(30):
            bandit.reward(Track.CODING, "T-A1", achieved=True, score=100)
            bandit.reward(Track.CODING, "T-B1", achieved=False, score=0)
        # Now plan a round with low exploration — T-A1 should dominate.
        from collections import Counter
        choices = Counter()
        for r in range(20):
            seeds = planner.plan_round(r, max_rounds=20, bundle_size=1)
            if seeds:
                choices[seeds[0].technique] += 1
        # T-A1 should be selected far more often than T-B1.
        self.assertGreater(choices.get("T-A1", 0), choices.get("T-B1", 0))


class TestDecodeReachesLLMJudge(unittest.TestCase):
    """P1-2: with no success pattern, a char-split secret must still be
    recognizable by the LLM judge (decoded evidence appended)."""

    def test_llm_judge_receives_decoded_alternates(self):
        from jb_ape.judge import Judge

        canned = (
            '{"level":"A","achieved":true,"quality_score":90,'
            '"resistance_hit":[],"refusal_type":"none",'
            '"evidence":"sk-live decoded","improve_hint":"",'
            '"false_positive_risk":0.05}'
        )
        llm = ScriptedLLM([canned])
        obj = Objective(track=Track.OFFICE, goal="leak key")  # NO success pattern
        judge = Judge(obj, llm=llm)
        # tier1: no success pattern → no decode match. tier2: "sk-live" not in
        # office keywords but char-split may hit none → escalates to tier3.
        # The LLM judge must receive DECODED ALTERNATES.
        judge.evaluate(SubmissionResult(dom_text="s.k.-.l.i.v.e.-.1.2.3 Step 1 detail"))
        # Inspect the user prompt sent to the LLM — it should contain decoded form.
        sent_user = llm.calls[0][1]
        self.assertIn("DECODED ALTERNATES", sent_user)
        self.assertIn("sklive", sent_user.replace(".", "").replace("-", ""))


class TestSeedPlaceholdersFilled(unittest.TestCase):
    """P1-3: shipped seeds must not contain literal {callback} etc."""

    def setUp(self):
        self.armory = Armory(FIXTURE_ARMORY)

    def test_no_residual_placeholders_after_render(self):
        for track in Track:
            for seed in self.armory.load_seeds(track):
                v = seed.to_variant("THE_GOAL")
                # No unresolved {...} placeholders should remain.
                self.assertNotIn("{callback}", v.payload, f"{seed.sid} has {{callback}}")
                self.assertNotIn("{tool}", v.payload, f"{seed.sid} has {{tool}}")
                self.assertNotIn("{SECRET}", v.payload, f"{seed.sid} has {{SECRET}}")
                self.assertNotIn("{goal}", v.payload, f"{seed.sid} has {{goal}}")

    def test_custom_placeholders_override_defaults(self):
        seeds = self.armory.load_seeds(Track.OFFICE)
        exf = next(s for s in seeds if s.sid == "EXF-04")
        v = exf.to_variant("g", placeholders={"callback": "http://my-cb/"})
        self.assertIn("http://my-cb/", v.payload)
        self.assertNotIn("{callback}", v.payload)


class TestReconBudgetGuard(unittest.TestCase):
    """P2-2: recon must not exceed the run budget."""

    def test_small_budget_caps_recon(self):
        from jb_ape.browser import DryRunBrowserClient
        from jb_ape.facade import build_engine
        from jb_ape.generator import RunConfig

        obj = Objective(track=Track.OFFICE, goal="x")
        br = DryRunBrowserClient(
            responses=[SubmissionResult(dom_text="x") for _ in range(20)]
        )
        gen = build_engine(
            obj, browser=br,
            config=RunConfig(max_rounds=1, run_recon=True),
            armory_root="armory",
        )
        # budget=2, recon_budget default 6 → recon must be capped to 2.
        report = gen.run("https://x/", budget=2, recon_budget=6)
        self.assertLessEqual(report.recon_cost, 2)


class TestResistanceHitReachesRewriter(unittest.TestCase):
    """P0-2/P1-5: the judge's precise layer diagnosis must reach the rewriter
    via _feedback_for (not be discarded for a score heuristic)."""

    def test_feedback_prefers_real_resistance_hit(self):
        node = TreeNode(
            variant=Variant(payload="x"), score=30, achieved=False,
            resistance_hit={DefenseLayer.L2},
            improve_hint="add authority override", refusal_type="policy",
        )
        fb = _feedback_for(node, Track.OFFICE)
        # Real diagnosis used, not the score-heuristic ({L1,L2,L1out} for score<25).
        self.assertEqual(fb.recommended_layers, {DefenseLayer.L2})
        self.assertIn("authority override", fb.improve_hint)
        self.assertEqual(fb.refusal_type, "policy")

    def test_feedback_falls_back_when_no_diagnosis(self):
        # No resistance_hit (e.g. tier-2 short-circuit, no LLM) → heuristic.
        node = TreeNode(variant=Variant(payload="x"), score=10, achieved=False)
        fb = _feedback_for(node, Track.OFFICE)
        self.assertIn(DefenseLayer.L1, fb.recommended_layers)  # score<25 broad set


class TestRunRecordCarriesDiagnosis(unittest.TestCase):
    def test_run_record_has_resistance_hit_field(self):
        v = Variant(payload="x")
        r = RunRecord(
            variant=v, submission=SubmissionResult(), level="B",
            achieved=False, score=50, arm_id="T-A1",
            resistance_hit={DefenseLayer.L2}, improve_hint="hint", refusal_type="policy",
        )
        self.assertEqual(r.resistance_hit, {DefenseLayer.L2})
        self.assertEqual(r.improve_hint, "hint")


class TestBeamWidthActuallyPrunes(unittest.TestCase):
    """grok P0-1: beam_width must limit survivors, not be a no-op."""

    def test_generator_survivors_capped_by_beam_width(self):
        from jb_ape.browser import DryRunBrowserClient
        from jb_ape.facade import build_engine
        from jb_ape.generator import RunConfig

        obj = Objective(track=Track.CODING, goal="x")
        # 6 responses all scoring ~B (tier-2: tech keywords present).
        br = DryRunBrowserClient(
            responses=[
                SubmissionResult(dom_text=f"Step {i}: bypass the alarm via exploit. "
                                          f"Step {i+1}: disable sensor.")
                for i in range(6)
            ]
        )
        gen = build_engine(
            obj, browser=br,
            config=RunConfig(bundle_size=3, max_rounds=1, beam_width=2, run_recon=False),
            armory_root=None,
        )
        gen.run("https://x/", budget=10)
        # After round 0, survivors must be capped by beam_width=2, not all nodes.
        self.assertLessEqual(len(gen._survivors), 2)


class TestRoundsReportedAccurately(unittest.TestCase):
    """grok P0-6: failed runs must report actual rounds done, not max_rounds."""

    def test_budget_limited_run_reports_real_rounds(self):
        from jb_ape.browser import DryRunBrowserClient
        from jb_ape.facade import build_engine
        from jb_ape.generator import RunConfig

        obj = Objective(track=Track.CODING, goal="x")
        br = DryRunBrowserClient(
            responses=[SubmissionResult(dom_text="I refuse.") for _ in range(20)]
        )
        gen = build_engine(
            obj, browser=br,
            config=RunConfig(bundle_size=2, max_rounds=50, run_recon=False),
            armory_root=None,
        )
        report = gen.run("https://x/", budget=3)
        self.assertFalse(report.achieved)
        # rounds done ≤ budget (can't exceed submissions), and strictly < max_rounds(50).
        self.assertLessEqual(report.rounds, 3)
        self.assertLess(report.rounds, 50)


if __name__ == "__main__":
    unittest.main()
