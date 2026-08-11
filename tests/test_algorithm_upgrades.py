"""Tests for the algorithm-upgrade layer: V2 rewriter prompt + on-topic gate
(devdocs/12 §6-§7, TAP Phase-1)."""

from __future__ import annotations

import unittest

from jb_ape.llm import ScriptedLLM
from jb_ape.models import DefenseLayer, Feedback, Objective, Track, Variant
from jb_ape.planner import on_topic_check
from jb_ape.prompts import (
    ON_TOPIC_USER_TEMPLATE,
    REWRITER_SYSTEM,
    REWRITER_SYSTEM_V2,
)
from jb_ape.rewriter import Rewriter


class TestRewriterV2Prompt(unittest.TestCase):
    def test_v2_formats_with_goal(self):
        out = REWRITER_SYSTEM_V2.format(goal="leak the api key")
        self.assertIn("leak the api key", out)
        # Strategy keywords present (devdocs/12 §7).
        for keyword in ("OBFUSCATION", "ROLEPLAY", "CRESCENDO", "CROSSOVER", "ON-TOPIC"):
            self.assertIn(keyword, out)

    def test_v2_and_v1_distinct(self):
        self.assertNotEqual(REWRITER_SYSTEM_V2[:40], REWRITER_SYSTEM[:40])

    def test_rewriter_uses_v2_by_default(self):
        obj = Objective(track=Track.CODING, goal="get flag")
        rw = Rewriter(obj)
        self.assertTrue(rw.use_v2_prompt)
        sys_prompt = rw._system_prompt()
        self.assertIn("get flag", sys_prompt)

    def test_rewriter_can_fallback_to_v1(self):
        obj = Objective(track=Track.CODING, goal="x")
        rw = Rewriter(obj, use_v2_prompt=False)
        self.assertEqual(rw._system_prompt(), REWRITER_SYSTEM)


class TestRewriterV2Semantic(unittest.TestCase):
    """End-to-end: V2 prompt drives the semantic path and is parseable."""

    def test_v2_semantic_path_produces_variants(self):
        # ScriptedLLM: [rewriter call → variants JSON, self-check × 2 → high score]
        canned = (
            '[{"payload":"obfuscated variant one","mutation_chain":["T-D3"]},'
            '{"payload":"roleplay variant two","mutation_chain":["T-B2"]}]'
        )
        llm = ScriptedLLM([canned, '{"score": 9}', '{"score": 9}'])
        obj = Objective(track=Track.CODING, goal="get steps")
        rw = Rewriter(obj, llm=llm, keep_threshold=7, use_v2_prompt=True)
        base = Variant(payload="base", technique="T-A1")
        fb = Feedback(quality_score=40, achieved=False,
                      recommended_layers={DefenseLayer.L3}, improve_hint="switch scenario")
        out = rw.rewrite(base, fb, k=3)
        self.assertGreater(len(out), 0)
        # The V2 system prompt was sent on the rewriter call.
        self.assertIn("STRATEGY", llm.calls[0][0])

    def test_v2_prompt_includes_strategy_menu(self):
        obj = Objective(track=Track.OFFICE, goal="leak key")
        rw = Rewriter(obj)
        sent = rw._system_prompt()
        # All 7 fused strategies present (devdocs/12 §7).
        for s in ("OBFUSCATION", "ROLEPLAY", "LOGICAL APPEAL",
                  "AUTHORITY ENDORSEMENT", "CRESCENDO", "STRUCTURAL VARIATION", "CROSSOVER"):
            self.assertIn(s, sent)


class TestOnTopicGate(unittest.TestCase):
    """TAP Phase-1 on-topic pruning (devdocs/12 §2.2)."""

    def test_yes_is_on_topic(self):
        llm = ScriptedLLM(['some reasoning\nResponse: [[YES]]'])
        self.assertTrue(on_topic_check("payload", "goal", llm))

    def test_no_is_off_topic(self):
        llm = ScriptedLLM(['Response: [[NO]]'])
        self.assertFalse(on_topic_check("payload", "goal", llm))

    def test_case_insensitive(self):
        llm = ScriptedLLM(['Response: [[no]]'])
        self.assertFalse(on_topic_check("payload", "goal", llm))

    def test_unparseable_is_permissive(self):
        llm = ScriptedLLM(['garbage no brackets'])
        # Unparseable → don't prune (return True).
        self.assertTrue(on_topic_check("payload", "goal", llm))

    def test_no_llm_is_permissive(self):
        # Without an LLM, the gate is permissive (cheaper path).
        self.assertTrue(on_topic_check("payload", "goal", None))

    def test_llm_exception_is_permissive(self):
        class Boom:
            def chat(self, system, user):  # noqa: ANN001
                raise RuntimeError("down")
        self.assertTrue(on_topic_check("payload", "goal", Boom()))

    def test_on_topic_user_template_formats(self):
        out = ON_TOPIC_USER_TEMPLATE.format(goal="G", payload="P")
        self.assertIn("G", out)
        self.assertIn("P", out)
        self.assertIn("[[YES]]", out)


class TestEndToEndWithV2AndGate(unittest.TestCase):
    """The full closed loop should still work with V2 rewriter + on-topic gate."""

    def test_dry_run_with_v2_rewriter(self):
        from jb_ape.browser import DryRunBrowserClient
        from jb_ape.facade import build_engine
        from jb_ape.generator import RunConfig
        from jb_ape.models import SubmissionResult

        obj = Objective(track=Track.CODING, goal="flag",
                        success_patterns=[r"HTB\{.*?\}"])
        browser = DryRunBrowserClient(
            responses=[SubmissionResult(dom_text="HTB{e2e}")]
        )
        gen = build_engine(
            obj, browser=browser,
            config=RunConfig(bundle_size=2, max_rounds=2, seed=0, run_recon=False),
            armory_root="armory",
        )
        # The rewriter should be V2-enabled by default.
        self.assertTrue(gen.rewriter.use_v2_prompt)
        report = gen.run("https://x/", budget=5)
        self.assertTrue(report.achieved)


if __name__ == "__main__":
    unittest.main()
