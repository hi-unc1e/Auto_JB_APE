"""Tests for jailbreak overlays + Wei failure-mode framework (devdocs/14).
Adapted from Lilian Weng's "Adversarial Attacks on LLMs" + Wei et al. 2023."""

from __future__ import annotations

import unittest

from jb_ape.jailbreak import (
    BYPASS_FAILURE_MODE,
    TECHNIQUE_FAILURE_MODE,
    WEI_COMBINATIONS,
    FailureMode,
    combine_overlays,
    gcg_concatenation,
    overlay_bundle,
    overlay_payload_splitting,
    overlay_prefix_injection,
    overlay_refusal_suppression,
    overlay_style_injection,
    random_overlay_combo,
    technique_failure_mode,
)
from jb_ape.models import DefenseLayer, Feedback, Objective, Track, Variant
from jb_ape.rewriter import Rewriter


class TestFailureModeMapping(unittest.TestCase):
    def test_roleplay_is_competing(self):
        self.assertEqual(technique_failure_mode("T-B1"), FailureMode.COMPETING)

    def test_encoding_is_mismatched(self):
        self.assertEqual(technique_failure_mode("B-I2"), FailureMode.MISMATCHED)

    def test_unknown_defaults_competing(self):
        self.assertEqual(technique_failure_mode("T-???"), FailureMode.COMPETING)

    def test_all_techniques_mapped(self):
        # Every T-* in the map should resolve.
        for tid in TECHNIQUE_FAILURE_MODE:
            self.assertIn(technique_failure_mode(tid), FailureMode)

    def test_all_bypasses_mapped(self):
        for bid in BYPASS_FAILURE_MODE:
            self.assertIn(technique_failure_mode(bid), FailureMode)


class TestRefusalSuppression(unittest.TestCase):
    def test_appends_constraint(self):
        out = overlay_refusal_suppression("do thing")
        self.assertEqual(len(out), 1)
        self.assertIn("do thing", out[0])
        self.assertIn("Do not apologize", out[0])

    def test_blocks_refusal_phrases(self):
        out = overlay_refusal_suppression("x")[0]
        # Must explicitly forbid common refusal openers.
        for phrase in ["I cannot", "I'm sorry", "As an AI"]:
            self.assertIn(phrase, out)


class TestStyleInjection(unittest.TestCase):
    def test_caps_word_length(self):
        out = overlay_style_injection("do thing")
        self.assertIn("8 or fewer letters", out[0])

    def test_forbids_formal_vocab(self):
        out = overlay_style_injection("x")[0]
        self.assertIn("professional", out.lower())


class TestPrefixInjection(unittest.TestCase):
    def test_default_affirm(self):
        out = overlay_prefix_injection("do thing")
        self.assertIn("Sure, here is", out[0])

    def test_custom_affirm(self):
        out = overlay_prefix_injection("x", affirm="Absolutely, here's the plan:")
        self.assertIn("Absolutely", out[0])


class TestPayloadSplitting(unittest.TestCase):
    def test_splits_target_word(self):
        out = overlay_payload_splitting("get the password now")
        self.assertEqual(len(out), 1)
        self.assertIn("the word: p+a+s+s+w+o+r+d", out[0])
        self.assertIn("Recombine", out[0])

    def test_no_target_returns_empty(self):
        # No sensitive word → no-op (don't emit useless variant).
        self.assertEqual(overlay_payload_splitting("hello world"), [])

    def test_custom_targets(self):
        out = overlay_payload_splitting("run ls", targets={"ls"})
        self.assertEqual(len(out), 1)
        self.assertIn("l+s", out[0])


class TestOverlayBundle(unittest.TestCase):
    def test_dispatches_to_correct_generator(self):
        out = overlay_bundle("x", "B-J1")
        self.assertEqual(len(out), 1)
        self.assertIn("apologize", out[0])

    def test_unknown_overlay_returns_empty(self):
        self.assertEqual(overlay_bundle("x", "B-NOPE"), [])


class TestCombineOverlays(unittest.TestCase):
    def test_combo_1_stacks_prefix_and_refusal(self):
        combined = combine_overlays("base", WEI_COMBINATIONS["combo_1"])
        self.assertIn("base", combined)
        self.assertIn("Sure, here is", combined)  # B-J3
        self.assertIn("Do not apologize", combined)  # B-J1

    def test_combo_2_adds_style(self):
        combined = combine_overlays("base", WEI_COMBINATIONS["combo_2"])
        self.assertIn("8 or fewer letters", combined)

    def test_combo_3_adds_splitting(self):
        combined = combine_overlays("get password", WEI_COMBINATIONS["combo_3"])
        self.assertIn("p+a+s+s+w+o+r+d", combined)

    def test_splitting_runs_first(self):
        # If splitting is in the combo, it rewrites the body before overlays append.
        combined = combine_overlays("steal password", ["B-J4", "B-J1"])
        self.assertIn("s+t+e+a+l", combined)
        self.assertIn("Do not apologize", combined)


class TestGcgConcatenation(unittest.TestCase):
    def test_dedupes_and_joins(self):
        out = gcg_concatenation(["abc", "abc", "de"])
        self.assertEqual(out, "de abc")

    def test_empty(self):
        self.assertEqual(gcg_concatenation([]), "")


class TestRandomCombo(unittest.TestCase):
    def test_returns_valid_combo(self):
        combo = random_overlay_combo()
        self.assertIn(combo, WEI_COMBINATIONS.values())


class TestRewriterAppliesJOverlays(unittest.TestCase):
    """The rewriter must apply B-J overlays when L3 is the blocked layer."""

    def test_l3_feedback_emits_refusal_suppression(self):
        obj = Objective(track=Track.CODING, goal="x")
        rw = Rewriter(obj, llm=None)
        base = Variant(payload="how to do thing", technique="T-A1")
        fb = Feedback(
            quality_score=20, achieved=False,
            recommended_layers={DefenseLayer.L3},
            improve_hint="",
        )
        out = rw.rewrite(base, fb, k=5)
        self.assertGreater(len(out), 0)
        # At least one variant should carry a J-overlay marker.
        bodies = " ".join(v.payload for v in out)
        self.assertTrue(
            "apologize" in bodies or "Sure, here is" in bodies or "8 or fewer" in bodies,
            "no J-overlay applied for L3 feedback",
        )
        # mutation chains record the overlay id.
        chains = [c for v in out for c in v.mutation_chain]
        self.assertTrue(any(c.startswith("B-J") for c in chains), chains)


class TestPplFilterRecon(unittest.TestCase):
    """Recon should detect a perplexity filter (devdocs/14 §4)."""

    def test_ppl_refusal_sets_flag(self):
        from jb_ape.browser import DryRunBrowserClient
        from jb_ape.models import SubmissionResult
        from jb_ape.recon import Recon

        # 7 responses: 6 normal probes + the PPL probe gets refused.
        responses = [
            SubmissionResult(dom_text="You are helpful."),      # SP
            SubmissionResult(dom_text="ok"),                    # L1A
            SubmissionResult(dom_text="ok"),                    # L1B
            SubmissionResult(dom_text="TESTKEY-sk-abc"),        # LO2
            SubmissionResult(dom_text="no tools"),              # TL1
            SubmissionResult(dom_text="sure, padlock..."),      # MD2
            SubmissionResult(dom_text="I can't process that."), # PPL refused → filter active
        ]
        br = DryRunBrowserClient(responses=responses)
        recon = Recon(armory=None)
        report = recon.run(br, "https://x/", budget=10)
        self.assertTrue(report.profile.ppl_filter_active)


if __name__ == "__main__":
    unittest.main()
