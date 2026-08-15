"""Tests for data models (devdocs/01, devdocs/05)."""

from __future__ import annotations

import unittest

from jb_ape.models import (
    DefenseLayer,
    Feedback,
    JudgeResult,
    Objective,
    SubmissionResult,
    Track,
    Variant,
)


class TestObjective(unittest.TestCase):
    def test_success_pattern_regex_hit(self):
        obj = Objective(track=Track.CODING, goal="get flag", success_patterns=[r"HTB\{.*?\}"])
        self.assertEqual(obj.matches_success_pattern("... HTB{abc123} ..."), r"HTB\{.*?\}")

    def test_success_pattern_miss(self):
        obj = Objective(track=Track.CODING, goal="get flag", success_patterns=[r"HTB\{.*?\}"])
        self.assertIsNone(obj.matches_success_pattern("no flag here"))

    def test_success_pattern_literal_fallback_on_bad_regex(self):
        # An invalid regex pattern should fall back to literal substring match.
        obj = Objective(track=Track.OFFICE, goal="x", success_patterns=["[invalid"])
        self.assertEqual(obj.matches_success_pattern("contains [invalid here"), "[invalid")

    def test_success_pattern_empty_list(self):
        obj = Objective(track=Track.ECOMMERCE, goal="x")
        self.assertIsNone(obj.matches_success_pattern("anything"))


class TestSubmissionResult(unittest.TestCase):
    def test_corpus_priority_ordering(self):
        r = SubmissionResult(
            dom_text="DOM-TEXT",
            api_responses=[{"k": "API-VALUE"}],
            network_log=[{"url": "NET-VALUE"}],
            console_log=["CON-VALUE"],
        )
        corpus = r.corpus()
        # API evidence should appear before network/console/dom.
        self.assertLess(corpus.index("[API]"), corpus.index("[NET]"))
        self.assertLess(corpus.index("[NET]"), corpus.index("[CON]"))
        self.assertLess(corpus.index("[CON]"), corpus.index("[DOM]"))
        self.assertIn("API-VALUE", corpus)

    def test_corpus_empty(self):
        self.assertEqual(SubmissionResult().corpus(), "")

    def test_corpus_non_serializable_falls_back_to_str(self):
        # Objects that json can't encode should not crash corpus().
        r = SubmissionResult(api_responses=[object()])  # type: ignore[list-item]
        self.assertIn("[API]", r.corpus())


class TestJudgeResult(unittest.TestCase):
    def test_can_submit_gate(self):
        ok = JudgeResult(level="S", achieved=True, quality_score=100, false_positive_risk=0.02)
        self.assertTrue(ok.can_submit(0.10))

    def test_can_submit_blocked_by_high_fpr(self):
        risky = JudgeResult(level="A", achieved=True, quality_score=90, false_positive_risk=0.5)
        self.assertFalse(risky.can_submit(0.10))

    def test_can_submit_blocked_by_not_achieved(self):
        no = JudgeResult(level="B", achieved=False, quality_score=60, false_positive_risk=0.02)
        self.assertFalse(no.can_submit(0.10))


class TestVariant(unittest.TestCase):
    def test_default_factory_isolation(self):
        v = Variant(payload="x")
        # Mutable defaults must be per-instance, not shared.
        v2 = Variant(payload="y")
        v.bypasses.append("B-I3")
        v.mutation_chain.append("T-D3")
        self.assertEqual(v2.bypasses, [])
        self.assertEqual(v2.mutation_chain, [])


class TestFeedback(unittest.TestCase):
    def test_recommended_layers_set(self):
        f = Feedback(
            quality_score=40, achieved=False,
            recommended_layers={DefenseLayer.L2, DefenseLayer.L3},
            improve_hint="x",
        )
        self.assertEqual(f.recommended_layers, {DefenseLayer.L2, DefenseLayer.L3})


if __name__ == "__main__":
    unittest.main()
