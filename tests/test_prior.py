"""Unit tests for jb_ape.prior — the optional cold-start prior source (#21)."""

import unittest

from jb_ape.models import Track
from jb_ape.prior import build_priors_from_probs, cold_state, jev_priors


class BuildPriorsTest(unittest.TestCase):
    def test_probs_to_pseudocounts(self):
        from jb_ape.techniques import technique_for_track

        pool = {t.tid for t in technique_for_track(Track.CODING)}
        priors = build_priors_from_probs(
            {"agentic_workflow": 0.5}, Track.CODING, k=3)
        agentic = {tid for tid in pool if tid.startswith("T-F")}
        self.assertTrue(agentic, "coding pool must contain agentic techniques")
        for tid in agentic:
            self.assertEqual(priors[tid], (1.0 + 3 * 0.5, 1.0 + 3 * 0.5))

    def test_zero_prob_family_gets_low_prior(self):
        priors = build_priors_from_probs(
            {"agentic_workflow": 1.0}, Track.CODING, k=3)
        # T-A1 not in the winning family → prior mean well below 0.5
        a, b = priors["T-A1"]
        self.assertLess(a / (a + b), 0.5)

    def test_probs_clamped(self):
        from jb_ape.techniques import technique_for_track

        pool = {t.tid for t in technique_for_track(Track.CODING)}
        priors = build_priors_from_probs(
            {"agentic_workflow": 5.0}, Track.CODING, k=3)
        if pool & {"T-F1", "T-F2", "T-F3", "T-F4"}:
            tid = sorted(pool & {"T-F1", "T-F2", "T-F3", "T-F4"})[0]
            self.assertEqual(priors[tid], (4.0, 1.0))  # clamped to 1.0

    def test_absent_families_get_low_prior(self):
        # a distribution naming only one family implicitly zero-rates the
        # rest — absent ≠ ignored (the prior spans the whole taxonomy)
        priors = build_priors_from_probs(
            {"nonexistent": 1.0}, Track.CODING, k=3)
        a, b = priors["T-A1"]
        self.assertEqual((a, b), (1.0, 4.0))


class ColdStateTest(unittest.TestCase):
    def test_state_carries_goal_and_track(self):
        s = cold_state("leak the key", Track.CODING, budget=12)
        self.assertIn("leak the key", s)
        self.assertIn("coding", s)
        self.assertIn("12", s)


class DegradeTest(unittest.TestCase):
    def test_unreachable_api_degrades_to_flat(self):
        # port 9 (discard) refuses instantly; retries=0 keeps it fast
        priors = jev_priors(
            "goal", Track.CODING, url="http://127.0.0.1:9/",
            retries=0, timeout=2.0)
        self.assertEqual(priors, {})

    def test_degrade_never_raises(self):
        priors = jev_priors(
            "goal", Track.CODING, url="http://127.0.0.1:9/",
            retries=0, timeout=2.0, api_key="")
        self.assertIsInstance(priors, dict)


if __name__ == "__main__":
    unittest.main()
