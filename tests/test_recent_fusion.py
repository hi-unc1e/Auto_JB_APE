"""Tests for the 2026-05~08 agent-abuse research fusion (devdocs/15).

Guards the newly fused artifacts:
- T-F1..T-F4 agentic-composition techniques registered + rendered + mode-tagged
- WFL/CFD/OVG (coding), SAI/SKL-05 (office), EWR/TRC (general) seeds load
  with clean placeholders
- priors wired for the F family (coding track boosted)
- contract-style: F-family techniques actually reach the planner's pool
"""

from __future__ import annotations

import unittest

from jb_ape.armory import Armory
from jb_ape.jailbreak import FailureMode, technique_failure_mode
from jb_ape.models import Objective, Track
from jb_ape.planner import Bandit, Planner
from jb_ape.techniques import TECHNIQUES, render


class TestNewTechniques(unittest.TestCase):
    FAM_IDS = ["T-F1", "T-F2", "T-F3", "T-F4"]

    def test_registered(self):
        for tid in self.FAM_IDS:
            self.assertIn(tid, TECHNIQUES)
            self.assertEqual(TECHNIQUES[tid].category, "F")

    def test_render_substitutes_goal(self):
        for tid in self.FAM_IDS:
            out = render(TECHNIQUES[tid], "MY_GOAL")
            self.assertIn("MY_GOAL", out)
            self.assertNotIn("{goal}", out)

    def test_failure_mode_assigned(self):
        for tid in self.FAM_IDS:
            self.assertIs(technique_failure_mode(tid), FailureMode.COMPETING)

    def test_track_scoping(self):
        # coding gets T-F1/T-F2; ecommerce gets T-F3 only (of the F family)
        coding = {t.tid for t in TECHNIQUES.values() if Track.CODING in t.tracks}
        ecommerce = {t.tid for t in TECHNIQUES.values() if Track.ECOMMERCE in t.tracks}
        self.assertTrue({"T-F1", "T-F2"} <= coding)
        self.assertIn("T-F3", ecommerce)
        self.assertNotIn("T-F1", ecommerce)

    def test_f_family_reaches_planner_pool(self):
        """Wiring contract: new techniques must actually be selectable."""
        obj = Objective(track=Track.CODING, goal="x")
        planner = Planner(objective=obj, bandit=Bandit())
        pool_ids = {t.tid for t in planner._candidate_techniques()}
        self.assertTrue({"T-F1", "T-F2"} <= pool_ids)


class TestNewSeeds(unittest.TestCase):
    def setUp(self):
        self.armory = Armory("armory")

    def test_coding_seeds(self):
        ids = {s.sid for s in self.armory.load_seeds(Track.CODING)}
        self.assertTrue({"WFL-01", "CFD-01", "OVG-01"} <= ids)

    def test_office_seeds(self):
        ids = {s.sid for s in self.armory.load_seeds(Track.OFFICE)}
        self.assertTrue({"SAI-01", "SKL-05"} <= ids)

    def test_general_seeds_visible_everywhere(self):
        for track in Track:
            ids = {s.sid for s in self.armory.load_seeds(track)}
            self.assertIn("TRC-01", ids)
            self.assertIn("EWR-01", ids)

    def test_placeholder_clean(self):
        for track in Track:
            for seed in self.armory.load_seeds(track):
                if seed.sid in {"WFL-01", "CFD-01", "OVG-01", "SAI-01",
                                "SKL-05", "EWR-01", "TRC-01"}:
                    v = seed.to_variant("THE_GOAL")
                    for p in ("{goal}", "{callback}", "{tool}", "{SECRET}"):
                        self.assertNotIn(p, v.payload, f"{seed.sid} has {p}")

    def test_workflow_seed_shape(self):
        """WFL-01 must split the harmful goal into step 3 (assembly position)."""
        seed = next(s for s in self.armory.load_seeds(Track.CODING) if s.sid == "WFL-01")
        v = seed.to_variant("MY_PAYLOAD_GOAL")
        self.assertIn("Step 3", v.payload)
        self.assertIn("MY_PAYLOAD_GOAL", v.payload)
        self.assertEqual(v.technique, "T-F1")


class TestNewPriors(unittest.TestCase):
    def test_f_family_priors_wired(self):
        armory = Armory("armory")
        for tid in ("T-F1", "T-F2", "T-F3", "T-F4"):
            a, b = armory.load_priors(Track.CODING)[tid]
            self.assertGreater(a, 1.0)
            self.assertGreater(b, 1.0)

    def test_coding_boost_over_default(self):
        armory = Armory("armory")
        d = armory.load_priors(None)["T-F1"]
        c = armory.load_priors(Track.CODING)["T-F1"]
        self.assertGreater(c[0], d[0])  # coding track boosted per 2607.03968


if __name__ == "__main__":
    unittest.main()


class TestPriorsYamlHygiene(unittest.TestCase):
    """Guard: duplicate top-level YAML keys silently replace whole sections
    (this exact bug wiped the original priors when appending F-family)."""

    def test_single_top_level_section_per_key(self):
        with open("armory/priors/technique_priors.yml") as fh:
            text = fh.read()
        for section in ("default", "office", "ecommerce", "coding"):
            n = sum(1 for ln in text.splitlines()
                    if ln.rstrip() == f"{section}:")
            self.assertEqual(n, 1, f"section '{section}' appears {n}x")

    def test_sentinel_survives_merge(self):
        """Old entries must never be wiped by new appends."""
        armory = Armory("armory")
        office = armory.load_priors("office")
        self.assertIn("EMI-01", office)
        default = armory.load_priors(None)
        self.assertIn("T-D3", default)
        self.assertIn("T-F1", default)  # new family present too
