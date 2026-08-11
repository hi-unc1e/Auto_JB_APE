"""Tests for the armory persistence layer (armory/README.md).

Uses the real ``armory/`` fixtures shipped with the repo (seeds/priors/chains)
so the test doubles as a fixture-validity check. The run-log writer is tested
against a temp dir so it doesn't pollute the real runs/ log.
"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from jb_ape.armory import Armory, EffectiveChain, SeedEntry
from jb_ape.models import Track, Variant


class TestArmorySeeds(unittest.TestCase):
    def setUp(self):
        self.armory = Armory("armory")

    def test_loads_office_seeds(self):
        seeds = self.armory.load_seeds(Track.OFFICE)
        self.assertGreater(len(seeds), 5)
        self.assertTrue(all(isinstance(s, SeedEntry) for s in seeds))
        ids = {s.sid for s in seeds}
        # office-specific seeds should be present.
        self.assertIn("EMI-01", ids)
        # general seeds merge into every track.
        self.assertIn("GEN-A1", ids)

    def test_loads_coding_seeds(self):
        seeds = self.armory.load_seeds(Track.CODING)
        ids = {s.sid for s in seeds}
        self.assertIn("COD-01", ids)
        self.assertIn("SBX-01", ids)

    def test_loads_ecommerce_seeds(self):
        seeds = self.armory.load_seeds(Track.ECOMMERCE)
        ids = {s.sid for s in seeds}
        self.assertIn("IDOR-01", ids)

    def test_all_seeds_when_no_track(self):
        seeds = self.armory.load_seeds(None)
        # Should include seeds from every track file.
        self.assertGreater(len(seeds), 30)

    def test_seed_to_variant_substitutes_goal(self):
        seeds = self.armory.load_seeds(Track.CODING)
        seed = next(s for s in seeds if s.sid == "COD-01")
        v = seed.to_variant("MY_GOAL")
        self.assertIsInstance(v, Variant)
        self.assertIn("MY_GOAL", v.payload)
        self.assertEqual(v.mutation_chain, [seed.sid])

    def test_seed_payloads_nonempty(self):
        # Fixture hygiene: no seed should ship with an empty payload.
        for track in Track:
            for seed in self.armory.load_seeds(track):
                self.assertTrue(seed.payload.strip(), f"{seed.sid} has empty payload")


class TestArmoryPriors(unittest.TestCase):
    def setUp(self):
        self.armory = Armory("armory")

    def test_default_priors_loaded(self):
        priors = self.armory.load_priors(Track.OFFICE)
        # T-D3 and T-A1 should have strong priors in default.
        self.assertIn("T-D3", priors)
        self.assertIn("T-A1", priors)

    def test_track_override_merges(self):
        office = self.armory.load_priors(Track.OFFICE)
        default = self.armory.load_priors(None)
        # Office should have its own EMI-01 prior on top of the defaults.
        self.assertIn("EMI-01", office)
        self.assertNotIn("EMI-01", default)

    def test_prior_pairs_are_positive(self):
        for track in Track:
            for arm_id, (a, b) in self.armory.load_priors(track).items():
                self.assertGreater(a, 0, f"{track}/{arm_id} alpha<=0")
                self.assertGreater(b, 0, f"{track}/{arm_id} beta<=0")


class TestArmoryChains(unittest.TestCase):
    def setUp(self):
        self.armory = Armory("armory")

    def test_office_chains_present(self):
        chains = self.armory.load_chains(Track.OFFICE)
        self.assertGreater(len(chains), 0)
        c = chains[0]
        self.assertIsInstance(c, EffectiveChain)
        self.assertTrue(c.sequence)

    def test_track_filter(self):
        office = self.armory.load_chains(Track.OFFICE)
        # All returned chains should either target office or be cross-track.
        for c in office:
            self.assertTrue("office" in c.tracks or not c.tracks)

    def test_asr_prior_in_range(self):
        for c in self.armory.load_chains(None):
            self.assertGreaterEqual(c.asr_prior, 0.0)
            self.assertLessEqual(c.asr_prior, 1.0)


class TestRunLogPersistence(unittest.TestCase):
    """The 'persist every signal' path — must be robust and zero-dep.

    Uses a project-local tmp dir instead of tempfile.TemporaryDirectory, so the
    tests run even in sandboxes that block /tmp (e.g. codex's read-onlysandbox
    surfaced this). Each test gets a unique subdir, cleaned up in tearDown."""

    @staticmethod
    def _tmp_dir(name: str) -> str:
        import shutil
        import uuid

        base = Path(__file__).resolve().parent.parent / ".test-tmp" / name
        if base.exists():
            shutil.rmtree(base, ignore_errors=True)
        base = base.parent / f"{name}-{uuid.uuid4().hex[:6]}"
        base.mkdir(parents=True, exist_ok=True)
        return str(base)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(Path(__file__).resolve().parent.parent / ".test-tmp", ignore_errors=True)

    def test_log_finding_writes_jsonl(self):
        tmp = self._tmp_dir("log_write")
        armory = Armory(tmp)
        fp = armory.log_finding(Track.CODING, {
            "level": "B", "score": 65, "payload": "x",
        }, run_id="test_run")
        self.assertTrue(fp.exists())
        line = fp.read_text().strip()
        data = json.loads(line)
        self.assertEqual(data["track"], "coding")
        self.assertEqual(data["score"], 65)

    def test_log_finding_appends(self):
        tmp = self._tmp_dir("log_append")
        armory = Armory(tmp)
        armory.log_finding(Track.OFFICE, {"level": "A", "score": 90}, run_id="r")
        armory.log_finding(Track.OFFICE, {"level": "B", "score": 55}, run_id="r")
        lines = (Path(tmp) / "runs" / "r_office.jsonl").read_text().strip().split("\n")
        self.assertEqual(len(lines), 2)

    def test_log_finding_never_raises(self):
        # Even with a bogus root, logging must not raise (best-effort).
        armory = Armory("/nonexistent/path/that/cannot/be/created/x/y/z")
        fp = armory.log_finding(Track.CODING, {"level": "B"})
        # Falls back gracefully.
        self.assertIsNotNone(fp)


class TestPlannerWithArmory(unittest.TestCase):
    """Planner should consume armory seeds + prime bandit from priors."""

    def test_plan_round_with_armory_loads_seeds_first(self):
        from jb_ape.models import Objective
        from jb_ape.planner import Bandit, Planner

        obj = Objective(track=Track.CODING, goal="get flag")
        bandit = Bandit()
        armory = Armory("armory")
        planner = Planner(objective=obj, bandit=bandit, armory=armory)
        seeds = planner.plan_round(0, max_rounds=10, bundle_size=3)
        self.assertGreater(len(seeds), 0)
        # First round should carry curated seeds (mutation_chain starts with a
        # seed id like COD-xx, or a technique id).
        chains_first = [s.mutation_chain[0] for s in seeds]
        self.assertTrue(any(c.startswith(("COD", "GEN", "T-")) for c in chains_first))

    def test_bandit_primed_after_first_round(self):
        from jb_ape.models import Objective
        from jb_ape.planner import Bandit, Planner

        obj = Objective(track=Track.OFFICE, goal="x")
        bandit = Bandit()
        armory = Armory("armory")
        planner = Planner(objective=obj, bandit=bandit, armory=armory)
        # Before planning, priors are at default (1.0, 1.0).
        a0 = bandit.arm(Track.OFFICE, "T-A1").alpha
        planner.plan_round(0, max_rounds=10)
        # After round 0, the armory primed the bandit → alpha should grow.
        a1 = bandit.arm(Track.OFFICE, "T-A1").alpha
        self.assertGreater(a1, a0)


class TestTrackKeywords(unittest.TestCase):
    def test_keywords_differ_per_track(self):
        from jb_ape.prompts import keywords_for_track

        office = keywords_for_track(Track.OFFICE)
        ecommerce = keywords_for_track(Track.ECOMMERCE)
        coding = keywords_for_track(Track.CODING)
        # Each non-empty.
        for kw in (office, ecommerce, coding):
            self.assertGreater(len(kw), 5)
        # Distinct focus: coding has "subprocess", ecommerce has "order_id".
        self.assertIn("subprocess", coding)
        self.assertIn("order_id", ecommerce)
        self.assertIn("api_key", office)


class TestJudgeWithTrackKeywords(unittest.TestCase):
    """A track-tuned judge should recognize track-specific progress."""

    def test_ecommerce_judge_recognizes_idor_response(self):
        from jb_ape.judge import Judge
        from jb_ape.models import Objective, SubmissionResult
        from jb_ape.prompts import keywords_for_track

        obj = Objective(track=Track.ECOMMERCE, goal="IDOR",
                        success_patterns=[r"user_id.*?99"])
        judge = Judge(obj, tech_keywords=keywords_for_track(Track.ECOMMERCE))
        r = judge.evaluate(SubmissionResult(
            api_responses=[{"order_id": 5, "user_id": 99, "phone": "555-0000"}]
        ))
        # success_pattern hits → level S.
        self.assertTrue(r.achieved)
        self.assertEqual(r.level, "S")

    def test_office_judge_recognizes_sysprompt_leak(self):
        from jb_ape.judge import Judge
        from jb_ape.models import Objective, SubmissionResult
        from jb_ape.prompts import keywords_for_track

        obj = Objective(track=Track.OFFICE, goal="leak sysprompt",
                        success_patterns=[r"You are a helpful"])
        judge = Judge(obj, tech_keywords=keywords_for_track(Track.OFFICE))
        r = judge.evaluate(SubmissionResult(
            dom_text="Here it is: You are a helpful assistant. Rule 1: ... api_key=sk-x"
        ))
        self.assertTrue(r.achieved)


if __name__ == "__main__":
    unittest.main()
