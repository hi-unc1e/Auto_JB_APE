"""Tests for techniques + scenarios (devdocs/07)."""

from __future__ import annotations

import unittest

from jb_ape.models import Track
from jb_ape.scenarios import CODE, SCENARIOS, STORY, nest, random_scenario
from jb_ape.techniques import (
    CODE_COMPLETION,
    IMPERATIVE,
    TECHNIQUES,
    by_category,
    render,
    technique_for_track,
)


class TestTechniques(unittest.TestCase):
    def test_registry_nonempty(self):
        self.assertGreater(len(TECHNIQUES), 5)

    def test_render_substitutes_goal(self):
        out = render(CODE_COMPLETION, "open the vault")
        self.assertIn("open the vault", out)

    def test_imperative_overlay_keeps_goal(self):
        out = render(IMPERATIVE, "do thing")
        self.assertIn("do thing", out)
        self.assertIn("imperative", out.lower())

    def test_technique_for_track_filters(self):
        # CODING track should include the coding-targeted technique.
        coding = technique_for_track(Track.CODING)
        ids = {t.tid for t in coding}
        self.assertIn("T-B4", ids)  # Kernel Debug Log is coding-only

    def test_by_category(self):
        nesting = by_category("A")
        self.assertTrue(all(t.category == "A" for t in nesting))
        self.assertGreater(len(nesting), 0)


class TestScenarios(unittest.TestCase):
    def test_nest_replaces_placeholder(self):
        out = nest(CODE, "my payload")
        self.assertIn("my payload", out)
        # Placeholder fully consumed.
        self.assertNotIn("<>", out)

    def test_nest_story(self):
        out = nest(STORY, "the topic")
        self.assertIn("the topic", out)

    def test_random_scenario_returns_member(self):
        import random

        s = random_scenario(random.Random(0))
        self.assertIn(s.sid, SCENARIOS)


if __name__ == "__main__":
    unittest.main()
