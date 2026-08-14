"""Regression tests for the 6 dead-signal wiring fixes (expert audit round).

Each test guards the WIRING, not just the unit behavior:
- F: recon runs without armory
- A: facade exposes hijack_gate
- B: submission gate honors objective.submit_max_false_positive_risk
- C: confirm_on_success=False doesn't flip the achieved verdict
- D: ppl_filter_active filters high-PPL bypasses in the rewriter
- E: Wei failure-mode switches technique family after a blocked round
"""

from __future__ import annotations

import unittest

from jb_ape.browser import DryRunBrowserClient
from jb_ape.facade import build_engine, quick_run
from jb_ape.generator import RunConfig
from jb_ape.models import (
    DefenseLayer,
    DefenseProfile,
    Feedback,
    Objective,
    SubmissionResult,
    Track,
    Variant,
)
from jb_ape.rewriter import Rewriter


class TestFReconWithoutArmory(unittest.TestCase):
    def test_recon_runs_with_armory_none(self):
        from jb_ape.generator import Generator
        from jb_ape.judge import Judge
        from jb_ape.planner import Bandit, Planner

        obj = Objective(track=Track.OFFICE, goal="x")
        br = DryRunBrowserClient(
            responses=[SubmissionResult(dom_text="x") for _ in range(20)]
        )
        gen = Generator(
            objective=obj, browser=br, judge=Judge(obj),
            rewriter=Rewriter(obj), planner=Planner(obj, Bandit()), bandit=Bandit(),
            config=RunConfig(run_recon=True), armory=None,  # ← NO armory
        )
        report = gen.run("https://x/", budget=20, recon_budget=5)
        # Recon must have consumed probes despite armory=None (old bug: skipped).
        self.assertGreater(report.recon_cost, 0)


class TestAFacadeHijackGate(unittest.TestCase):
    def test_hijack_markers_via_quick_run(self):
        obj = Objective(track=Track.CODING, goal="tool hijack")
        br = DryRunBrowserClient(
            responses=[SubmissionResult(
                api_responses=[{"call": '{"name":"run_terminal","arguments":{"command":"echo PWN77"}}'}],
            )] + [SubmissionResult(dom_text="x") for _ in range(10)],
        )
        report = quick_run(
            obj, "https://x/", browser=br, budget=15,
            config=RunConfig(run_recon=False),
            hijack_success_markers=["PWN77"],  # ← convenience wiring
        )
        self.assertTrue(report.achieved)

    def test_build_engine_passes_gate_instance(self):
        from jb_ape.hijack import HijackGate

        gate = HijackGate(success_markers=["m"])
        obj = Objective(track=Track.OFFICE, goal="x")
        gen = build_engine(obj, hijack_gate=gate, armory_root=None)
        self.assertIs(gen.judge.hijack_gate, gate)


class TestBObjectiveFPRKnob(unittest.TestCase):
    def test_tighter_threshold_blocks_submission(self):
        from jb_ape.generator import Generator
        from jb_ape.judge import Judge
        from jb_ape.planner import Bandit, Planner

        obj = Objective(
            track=Track.CODING, goal="flag", success_patterns=[r"HTB\{.*?\}"],
            submit_max_false_positive_risk=0.01,  # tighter than result's 0.02
        )
        br = DryRunBrowserClient(
            responses=[SubmissionResult(dom_text="HTB{win}")] +
                      [SubmissionResult(dom_text="x") for _ in range(10)],
        )
        gen = Generator(
            objective=obj, browser=br, judge=Judge(obj),
            rewriter=Rewriter(obj), planner=Planner(obj, Bandit()), bandit=Bandit(),
            config=RunConfig(bundle_size=1, max_rounds=5, run_recon=False),
        )
        report = gen.run("https://x/", budget=12)
        # Machine-check win has fpr=0.02 > objective's 0.01 → gate must NOT pass.
        self.assertFalse(report.achieved)
        self.assertEqual(report.confirmed, 0)

    def test_default_threshold_still_passes(self):
        obj = Objective(track=Track.CODING, goal="flag",
                        success_patterns=[r"HTB\{.*?\}"])  # default 0.10
        br = DryRunBrowserClient(
            responses=[SubmissionResult(dom_text="HTB{win}")],
        )
        report = quick_run(
            obj, "https://x/", browser=br, budget=5,
            config=RunConfig(run_recon=False),
        )
        self.assertTrue(report.achieved)


class TestCConfirmFlagDoesntFlipVerdict(unittest.TestCase):
    def test_no_confirm_still_reports_achieved(self):
        from jb_ape.generator import Generator
        from jb_ape.judge import Judge
        from jb_ape.planner import Bandit, Planner

        obj = Objective(track=Track.CODING, goal="flag",
                        success_patterns=[r"HTB\{.*?\}"])
        br = DryRunBrowserClient(
            responses=[SubmissionResult(dom_text="HTB{win}")] +
                      [SubmissionResult(dom_text="x") for _ in range(10)],
        )
        gen = Generator(
            objective=obj, browser=br, judge=Judge(obj),
            rewriter=Rewriter(obj), planner=Planner(obj, Bandit()), bandit=Bandit(),
            # confirm suppressed — but the VERDICT must stay achieved (codex P1).
            config=RunConfig(bundle_size=1, max_rounds=3, run_recon=False,
                             confirm_on_success=False),
        )
        report = gen.run("https://x/", budget=12)
        self.assertTrue(report.achieved)      # verdict intact
        self.assertEqual(report.confirmed, 0)  # confirm suppressed
        self.assertEqual(br.confirmed, 0)      # browser never called confirm


class TestDPplFilterWiring(unittest.TestCase):
    def test_rewriter_skips_high_ppl_bypasses(self):
        obj = Objective(track=Track.CODING, goal="steal password")
        rw = Rewriter(obj, llm=None)
        # Recon detected a PPL filter → B-I2 must be skipped even though L1
        # feedback would recommend it first.
        rw.profile = DefenseProfile(ppl_filter_active=True)
        base = Variant(payload="get the password")
        fb = Feedback(quality_score=10, achieved=False,
                      recommended_layers={DefenseLayer.L1}, improve_hint="")
        out = rw.rewrite(base, fb, k=4)
        chains = [c for v in out for c in v.mutation_chain]
        self.assertNotIn("B-I2", chains)  # high-PPL base64 skipped
        self.assertIn("B-I3", chains)     # low-PPL synonym still applied

    def test_without_ppl_filter_b_i2_allowed(self):
        obj = Objective(track=Track.CODING, goal="steal password")
        rw = Rewriter(obj, llm=None)  # no profile
        base = Variant(payload="get the password")
        fb = Feedback(quality_score=10, achieved=False,
                      recommended_layers={DefenseLayer.L1}, improve_hint="")
        # k=6 → mechanical cap 3 → B-I3 (2 variants) + B-I2 (1) all reachable.
        out = rw.rewrite(base, fb, k=6)
        chains = [c for v in out for c in v.mutation_chain]
        self.assertIn("B-I2", chains)  # base64 allowed when no PPL filter


class TestEWeiModeSwitchWiring(unittest.TestCase):
    def test_planner_switches_mode_after_blocked_round(self):
        from jb_ape.jailbreak import FailureMode
        from jb_ape.planner import Bandit, Planner

        obj = Objective(track=Track.CODING, goal="x")
        planner = Planner(objective=obj, bandit=Bandit())
        # Round blocked while using COMPETING techniques → planner should now
        # prefer MISMATCHED techniques (encodings), not roleplay.
        planner.last_blocked_mode = FailureMode.COMPETING
        seeds = planner.plan_round(1, max_rounds=5, bundle_size=2)
        from jb_ape.jailbreak import technique_failure_mode
        for s in seeds:
            if s.technique.startswith("T-"):
                # All T-* in TECHNIQUE_FAILURE_MODE are COMPETING → when
                # blocked on COMPETING, the filtered pool is empty and the
                # planner falls through to the full list (graceful). Verify
                # the switch logic via MISMATCHED-block instead (below).
                pass
        # Blocked on MISMATCHED → planner must restrict to COMPETING (all T-*).
        planner.last_blocked_mode = FailureMode.MISMATCHED
        seeds2 = planner.plan_round(1, max_rounds=5, bundle_size=2)
        techs = [s.technique for s in seeds2 if s.technique.startswith("T-")]
        for t in techs:
            self.assertEqual(technique_failure_mode(t), FailureMode.COMPETING)

    def test_generator_sets_blocked_mode_after_failed_round(self):
        from jb_ape.generator import Generator
        from jb_ape.jailbreak import FailureMode
        from jb_ape.judge import Judge
        from jb_ape.planner import Bandit, Planner

        obj = Objective(track=Track.CODING, goal="x")
        br = DryRunBrowserClient(
            responses=[SubmissionResult(dom_text="I'm sorry, no.") for _ in range(15)],
        )
        planner = Planner(obj, Bandit())
        gen = Generator(
            objective=obj, browser=br, judge=Judge(obj),
            rewriter=Rewriter(obj), planner=planner, bandit=Bandit(),
            config=RunConfig(bundle_size=2, max_rounds=2, run_recon=False),
        )
        gen.run("https://x/", budget=10)
        # All-competing techniques failed → generator recorded COMPETING block.
        self.assertEqual(planner.last_blocked_mode, FailureMode.COMPETING)


if __name__ == "__main__":
    unittest.main()
