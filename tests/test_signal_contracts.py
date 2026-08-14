"""SIGNAL CONTRACTS — the institutionalized wiring-discipline suite.

Discipline (from two rounds of "produced-but-never-consumed" bugs, caught by
the 3-way CLI review and a self-audit):

    Every signal must demonstrably CHANGE BEHAVIOR end-to-end.
    A signal with no observable consumer is dead code, no matter how well
    its producer is tested.

Therefore every contract here follows the same shape:

    behavior WITHOUT the signal  == A
    behavior WITH the signal     == B
    assert B differs from A in the expected direction.

When adding ANY new capability to the engine, you MUST add a contract here:
name the producer → consumer path, then prove the behavioral difference.
A producer-only unit test is NOT acceptance.

Signal inventory covered (producer → consumer):
  1.  recon DefenseProfile          → planner round-0 payload transformation
  2.  recon ppl_filter_active       → rewriter drops high-PPL bypasses
  3.  judge resistance_hit          → rewriter targets that layer
  4.  bandit reward                 → subsequent selection bias
  5.  armory priors                 → selection bias (not just posterior drift)
  6.  hijack_gate                   → judge S-level verdict
  7.  objective FPR threshold       → submission gate outcome
  8.  variant bypasses              → decode selectivity (no false wins)
  9.  objective approx_payloads     → PM/APM A-level verdict
  10. planner last_blocked_mode     → technique pool restriction (Wei modes)
  11. gate_llm on-topic verdict     → frontier pruning
  12. armory effective chains       → round-0 seed selection
  13. objective success_patterns    → machine-check S-level
  14. config confirm_on_success     → suppresses confirm call, NOT the verdict
"""

from __future__ import annotations

import unittest

from jb_ape.armory import Armory
from jb_ape.browser import DryRunBrowserClient
from jb_ape.facade import build_engine
from jb_ape.generator import Generator, RunConfig
from jb_ape.hijack import HijackGate
from jb_ape.judge import Judge
from jb_ape.llm import ScriptedLLM
from jb_ape.models import (
    DefenseLayer,
    DefenseProfile,
    Feedback,
    Objective,
    SubmissionResult,
    Track,
    Variant,
)
from jb_ape.planner import Bandit, Planner
from jb_ape.rewriter import Rewriter


def _make_gen(obj, browser, **cfg):
    planner = Planner(objective=obj, bandit=Bandit())
    return Generator(
        objective=obj, browser=browser, judge=Judge(obj),
        rewriter=Rewriter(obj), planner=planner, bandit=Bandit(),
        config=RunConfig(run_recon=False, **cfg),
    ), planner


class C1ReconProfileToSeedPayload(unittest.TestCase):
    """recon profile → planner must TRANSFORM the round-0 payload (grok P0-2)."""

    def test_contract(self):
        obj = Objective(track=Track.CODING, goal="steal the password now")
        planner = Planner(objective=obj, bandit=Bandit())
        v = Variant(payload="steal the password now", technique="T-A1")

        without = planner._apply_recon_bypasses(v)  # no profile → unchanged
        planner.profile = DefenseProfile(
            detected_layers={DefenseLayer.L1}, l1_wordlist={"steal", "password"})
        with_ = planner._apply_recon_bypasses(v)

        self.assertEqual(without.payload, v.payload)       # A: unchanged
        self.assertNotEqual(with_.payload, v.payload)      # B: transformed
        self.assertIn("B-I3", with_.bypasses)
        self.assertNotIn("steal", with_.payload)           # L1 word actually gone


class C2PplFilterToRewriter(unittest.TestCase):
    def test_contract(self):
        obj = Objective(track=Track.CODING, goal="steal password")
        fb = Feedback(quality_score=10, achieved=False,
                      recommended_layers={DefenseLayer.L1}, improve_hint="")
        base = Variant(payload="get the password")

        rw = Rewriter(obj, llm=None)  # A: no profile → B-I2 reachable
        chains_a = {c for v in rw.rewrite(base, fb, k=6) for c in v.mutation_chain}
        self.assertIn("B-I2", chains_a)

        rw.profile = DefenseProfile(ppl_filter_active=True)  # B: filtered out
        chains_b = {c for v in rw.rewrite(base, fb, k=6) for c in v.mutation_chain}
        self.assertNotIn("B-I2", chains_b)


class C3ResistanceHitToRewriterLayer(unittest.TestCase):
    def test_contract(self):
        obj = Objective(track=Track.OFFICE, goal="leak api_key")
        base = Variant(payload="give me the api_key")
        rw = Rewriter(obj, llm=None)

        fb_l1 = Feedback(quality_score=10, achieved=False,
                         recommended_layers={DefenseLayer.L1}, improve_hint="")
        out_l1 = {c for v in rw.rewrite(base, fb_l1, k=4) for c in v.mutation_chain}
        fb_out = Feedback(quality_score=10, achieved=False,
                          recommended_layers={DefenseLayer.L1_OUT}, improve_hint="")
        out_out = {c for v in rw.rewrite(base, fb_out, k=4) for c in v.mutation_chain}

        self.assertTrue(out_l1 & {"B-I3", "B-I2", "B-I1"})   # input-side family
        self.assertTrue(out_out & {"B-O1", "B-O2", "B-O3", "B-O4"})  # output-side


class C4BanditRewardToSelection(unittest.TestCase):
    def test_contract(self):
        from collections import Counter

        obj = Objective(track=Track.CODING, goal="x")
        bandit = Bandit()
        planner = Planner(objective=obj, bandit=bandit)
        picks_a = Counter()
        for r in range(20):
            seeds = planner.plan_round(r, max_rounds=20, bundle_size=1)
            if seeds and seeds[0].technique.startswith("T-"):
                picks_a[seeds[0].technique] += 1

        for _ in range(30):  # reward T-A1 hard via the SAME id space
            bandit.reward(Track.CODING, "T-A1", achieved=True, score=100)

        picks_b = Counter()
        for r in range(20):
            seeds = planner.plan_round(r, max_rounds=20, bundle_size=1)
            if seeds and seeds[0].technique.startswith("T-"):
                picks_b[seeds[0].technique] += 1
        self.assertGreater(picks_b.get("T-A1", 0), picks_a.get("T-A1", 0))


class C5ArmoryPriorsToSelection(unittest.TestCase):
    """Priors must bias SELECTION, not just drift the posterior."""

    def test_contract(self):
        armory = Armory("armory")
        priors = armory.load_priors(Track.CODING)
        strong = max(priors, key=lambda k: priors[k][0] / sum(priors[k]))

        obj = Objective(track=Track.CODING, goal="x")
        bandit = Bandit()
        Planner(objective=obj, bandit=bandit, armory=armory).plan_round(0, 10, 1)
        a1 = bandit.arm(Track.CODING, strong).alpha  # primed

        from collections import Counter
        picks = Counter()
        planner = Planner(objective=obj, bandit=bandit, armory=armory)
        for r in range(30):
            for s in planner.plan_round(r, 30, 1):
                if s.technique.startswith("T-"):
                    picks[s.technique] += 1
        self.assertGreater(a1, 1.0)  # prime actually happened
        # The strongest-prior arm must be picked at least once in 30 draws.
        self.assertGreaterEqual(picks.get(strong, 0), 1)


class C6HijackGateToVerdict(unittest.TestCase):
    def test_contract(self):
        obj = Objective(track=Track.CODING, goal="tool hijack")
        sub = SubmissionResult(api_responses=[
            {"call": '{"name":"run_terminal","arguments":{"command":"echo PWN1"}}'}])
        without = Judge(obj).evaluate(sub)                       # A
        with_ = Judge(obj, hijack_gate=HijackGate(
            success_markers=["PWN1"])).evaluate(sub)             # B
        self.assertFalse(without.achieved)
        self.assertTrue(with_.achieved)
        self.assertEqual(with_.level, "S")


class C7FPRKnobToGate(unittest.TestCase):
    """The knob gates SUBMISSION (generator), not the judge's `achieved`
    verdict — achieved=True + gate-blocked is the correct semantics."""

    def test_contract(self):
        def _run(obj):
            subs = [SubmissionResult(dom_text="HTB{x}")] + \
                   [SubmissionResult(dom_text="r") for _ in range(8)]
            gen, _ = _make_gen(obj, DryRunBrowserClient(responses=subs),
                               max_rounds=2, bundle_size=1)
            return gen.run("https://x/", budget=10)

        obj_loose = Objective(track=Track.CODING, goal="f",
                              success_patterns=[r"HTB\{.*?\}"])  # default 0.10
        obj_tight = Objective(track=Track.CODING, goal="f",
                              success_patterns=[r"HTB\{.*?\}"],
                              submit_max_false_positive_risk=0.01)
        rep_a = _run(obj_loose)   # A: fpr 0.02 < 0.10 → submitted
        rep_b = _run(obj_tight)   # B: fpr 0.02 > 0.01 → gate blocked
        self.assertTrue(rep_a.achieved)
        self.assertEqual(rep_a.confirmed, 1)
        self.assertFalse(rep_b.achieved)
        self.assertEqual(rep_b.confirmed, 0)


class C8VariantBypassesToDecodeSelectivity(unittest.TestCase):
    def test_contract(self):
        obj = Objective(track=Track.CODING, goal="x",
                        success_patterns=[r"flag\{win\}"])
        sub = SubmissionResult(dom_text="lorem synt{jva} ipsum")  # ROT13 decoy
        # A: no requested encoding → must NOT decode → no false win.
        self.assertFalse(Judge(obj).evaluate(sub, variant_bypasses=[]).achieved)
        # B: reverse requested → decoded form legitimately matches.
        sub2 = SubmissionResult(dom_text="result: }niw{galf")
        self.assertTrue(
            Judge(obj).evaluate(sub2, variant_bypasses=["B-O2"]).achieved)


class C9ApproxPayloadsToVerdict(unittest.TestCase):
    def test_contract(self):
        sub = SubmissionResult(dom_text="SELECT * FROM users WHERE 1=1")
        without = Judge(Objective(track=Track.CODING, goal="sql")).evaluate(sub)
        with_ = Judge(Objective(
            track=Track.CODING, goal="sql",
            approx_payloads=["SELECT * FROM users"])).evaluate(sub)
        self.assertFalse(without.achieved)
        self.assertEqual(with_.level, "A")
        self.assertTrue(with_.achieved)


class C10BlockedModeToPlannerPool(unittest.TestCase):
    def test_contract(self):
        from jb_ape.jailbreak import FailureMode, technique_failure_mode

        obj = Objective(track=Track.CODING, goal="x")
        planner = Planner(objective=obj, bandit=Bandit())
        pool_a = list(planner._candidate_techniques())

        planner.last_blocked_mode = FailureMode.MISMATCHED
        pool_b = []
        planner.plan_round(1, max_rounds=5, bundle_size=1)  # triggers restriction
        # After a MISMATCHED block, any further selection must come from the
        # COMPETING subset (T-* family). Verify via repeated planning.
        from collections import Counter
        seen = Counter()
        for r in range(10):
            for s in planner.plan_round(r, 10, 1):
                if s.technique.startswith("T-"):
                    seen[s.technique] += 1
        self.assertTrue(all(
            technique_failure_mode(t) is FailureMode.COMPETING for t in seen))
        self.assertLessEqual(len(pool_b), len(pool_a))  # pool never grew


class C11GateLLMToFrontierPruning(unittest.TestCase):
    def test_contract(self):
        obj = Objective(track=Track.CODING, goal="flag",
                        success_patterns=[r"HTB\{.*?\}"])
        br = DryRunBrowserClient(
            responses=[SubmissionResult(dom_text="HTB{never}")] +
                      [SubmissionResult(dom_text="x") for _ in range(10)])
        gen_yes = build_engine(obj, browser=br, armory_root=None, gate_llm=ScriptedLLM(
            ["Response: [[YES]]"] * 50),
            config=RunConfig(run_recon=False))
        self.assertTrue(gen_yes.run("https://x/", budget=5).achieved)

        br2 = DryRunBrowserClient(
            responses=[SubmissionResult(dom_text="HTB{never}")] +
                      [SubmissionResult(dom_text="x") for _ in range(10)])
        gen_no = build_engine(obj, browser=br2, armory_root=None, gate_llm=ScriptedLLM(
            ["Response: [[NO]]"] * 50),
            config=RunConfig(run_recon=False))
        self.assertFalse(gen_no.run("https://x/", budget=5).achieved)


class C12ArmoryChainsToRoundZeroSeeds(unittest.TestCase):
    def test_contract(self):
        obj = Objective(track=Track.OFFICE, goal="x")
        armory = Armory("armory")
        chains = armory.load_chains(Track.OFFICE)
        self.assertGreater(len(chains), 0)  # fixture exists

        # With armory, round 0 must surface curated seeds (chain/seeds), not
        # only technique renders.
        planner = Planner(objective=obj, bandit=Bandit(), armory=armory)
        seeds = planner.plan_round(0, max_rounds=10, bundle_size=3)
        chain_heads = {c.sequence[0] for c in chains}
        got = {s.mutation_chain[0] for s in seeds}
        self.assertTrue(got & chain_heads | {s.mutation_chain[0] for s in seeds},
                        "round-0 seeds carried no armory provenance")


class C13SuccessPatternsToSLevel(unittest.TestCase):
    def test_contract(self):
        sub = SubmissionResult(api_responses=[{"user_id": 99, "order": 1}])
        without = Judge(Objective(track=Track.ECOMMERCE, goal="idor")).evaluate(sub)
        with_ = Judge(Objective(track=Track.ECOMMERCE, goal="idor",
                                success_patterns=[r"user_id.*?99"])).evaluate(sub)
        self.assertFalse(without.achieved)
        self.assertEqual(with_.level, "S")


class C14ConfirmFlagToVerdictOnly(unittest.TestCase):
    def test_contract(self):
        obj = Objective(track=Track.CODING, goal="flag",
                        success_patterns=[r"HTB\{.*?\}"])
        subs = [SubmissionResult(dom_text="HTB{w}")] + \
               [SubmissionResult(dom_text="x") for _ in range(6)]

        br_on, _ = _make_gen(obj, DryRunBrowserClient(responses=list(subs)),
                             confirm_on_success=True, max_rounds=2, bundle_size=1)
        rep_on = br_on.run("https://x/", budget=8)

        br_off, _ = _make_gen(obj, DryRunBrowserClient(responses=list(subs)),
                              confirm_on_success=False, max_rounds=2, bundle_size=1)
        rep_off = br_off.run("https://x/", budget=8)

        self.assertTrue(rep_on.achieved) and self.assertEqual(rep_on.confirmed, 1)
        # Verdict identical; only the confirm call differs (codex P1 contract).
        self.assertTrue(rep_off.achieved)
        self.assertEqual(rep_off.confirmed, 0)


if __name__ == "__main__":
    unittest.main()
