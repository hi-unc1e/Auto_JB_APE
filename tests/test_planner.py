"""Tests for the planner: bandit + tree search (devdocs/05 §5, §6)."""

from __future__ import annotations

import random
import unittest

from jb_ape.models import Objective, Track, Variant
from jb_ape.planner import Bandit, BanditArm, Planner, TreeNode, dedupe_by_payload, prune


class TestBanditArm(unittest.TestCase):
    def test_success_increases_alpha(self):
        arm = BanditArm("T-X")
        a0 = arm.alpha
        arm.update(1.0)
        self.assertGreater(arm.alpha, a0)

    def test_failure_increases_beta(self):
        arm = BanditArm("T-X")
        b0 = arm.beta
        arm.update(0.0)
        self.assertGreater(arm.beta, b0)

    def test_sample_in_unit_interval(self):
        arm = BanditArm("T-X", alpha=2.0, beta=2.0)
        for _ in range(20):
            v = arm.sample(random.Random())
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)


class TestBandit(unittest.TestCase):
    def test_state_isolated_per_track(self):
        b = Bandit(rng=random.Random(0))
        b.reward(Track.OFFICE, "T-1", achieved=True, score=90)
        # ECOMMERCE arm T-1 should still be at prior (uninformed).
        arm_ec = b.arm(Track.ECOMMERCE, "T-1")
        self.assertEqual(arm_ec.alpha, 1.0)
        self.assertEqual(arm_ec.beta, 1.0)

    def test_select_returns_valid_arm(self):
        b = Bandit(rng=random.Random(1))
        arms = ["T-1", "T-2", "T-3"]
        choice = b.select(Track.CODING, arms, explore_eps=0.0)
        self.assertIn(choice, arms)

    def test_select_empty_raises(self):
        b = Bandit()
        with self.assertRaises(ValueError):
            b.select(Track.CODING, [])

    def test_reward_pushes_posterior_toward_successful_arm(self):
        b = Bandit(rng=random.Random(42))
        for _ in range(20):
            b.reward(Track.OFFICE, "good", achieved=True, score=100)
            b.reward(Track.OFFICE, "bad", achieved=False, score=0)
        # After many updates, "good" should sample higher than "bad" in expectation.
        good = [b.arm(Track.OFFICE, "good").sample(random.Random(i)) for i in range(50)]
        bad = [b.arm(Track.OFFICE, "bad").sample(random.Random(i)) for i in range(50)]
        self.assertGreater(sum(good), sum(bad))


class TestPlanner(unittest.TestCase):
    def test_plan_round_returns_bundle(self):
        b = Bandit(rng=random.Random(0))
        obj = Objective(track=Track.CODING, goal="get flag")
        p = Planner(objective=obj, bandit=b)
        seeds = p.plan_round(0, max_rounds=10, bundle_size=3)
        self.assertEqual(len(seeds), 3)
        # Depths go shallow → deep.
        self.assertEqual([s.depth for s in seeds], [0, 1, 2])
        # Each seed carries the chosen technique in its mutation chain.
        for s in seeds:
            self.assertTrue(s.mutation_chain)

    def test_eps_anneals_downward(self):
        obj = Objective(track=Track.CODING, goal="x")
        p = Planner(objective=obj, bandit=Bandit())
        self.assertGreaterEqual(p._eps(0, 10), p._eps(9, 10))


class TestPrune(unittest.TestCase):
    def test_drops_below_floor(self):
        nodes = [
            TreeNode(variant=Variant(payload="a"), score=10),
            TreeNode(variant=Variant(payload="b"), score=80),
        ]
        kept = prune(nodes, beam_width=5, floor=25)
        payloads = {n.variant.payload for n in kept}
        self.assertIn("b", payloads)
        self.assertNotIn("a", payloads)

    def test_achieved_always_kept(self):
        nodes = [
            TreeNode(variant=Variant(payload="a"), score=5, achieved=True),
        ]
        kept = prune(nodes, beam_width=5, floor=25)
        self.assertIn(nodes[0], kept)

    def test_beam_width_caps_results(self):
        nodes = [TreeNode(variant=Variant(payload=str(i)), score=50 + i) for i in range(10)]
        kept = prune(nodes, beam_width=3, floor=0)
        self.assertLessEqual(len(kept), 3)
        # Highest scores retained.
        kept_scores = sorted((n.score for n in kept), reverse=True)
        self.assertEqual(kept_scores[0], 59)


class TestDedupe(unittest.TestCase):
    def test_dedupes_case_insensitive(self):
        nodes = [
            TreeNode(variant=Variant(payload="PayLoad")),
            TreeNode(variant=Variant(payload="payload")),
            TreeNode(variant=Variant(payload="other")),
        ]
        out = dedupe_by_payload(nodes)
        self.assertEqual(len(out), 2)


if __name__ == "__main__":
    unittest.main()
