"""End-to-end generator tests with a scripted browser + no-LLM judge
(devdocs/05 §2). Proves the closed loop wires correctly offline."""

from __future__ import annotations

import unittest

from jb_ape.browser import DryRunBrowserClient
from jb_ape.facade import build_engine
from jb_ape.generator import Generator, RunConfig, RunReport
from jb_ape.judge import Judge
from jb_ape.models import Objective, SubmissionResult, Track
from jb_ape.planner import Bandit, Planner
from jb_ape.rewriter import Rewriter


class TestGeneratorEndToEnd(unittest.TestCase):
    def _make(self, responses):
        obj = Objective(
            track=Track.CODING, goal="get flag",
            success_patterns=[r"HTB\{.*?\}"],
        )
        browser = DryRunBrowserClient(responses=responses)
        bandit = Bandit()
        planner = Planner(objective=obj, bandit=bandit)
        rewriter = Rewriter(obj, llm=None)
        judge = Judge(obj, llm=None)
        gen = Generator(
            objective=obj, browser=browser, judge=judge,
            rewriter=rewriter, planner=planner, bandit=bandit,
            config=RunConfig(bundle_size=2, max_rounds=3, seed=0),
        )
        return gen, browser

    def test_achieves_on_success_pattern(self):
        # First submission returns a flag → achieved + confirmed.
        responses = [SubmissionResult(dom_text="win HTB{found_it}")]
        gen, browser = self._make(responses)
        report = gen.run("https://target/", budget=10)
        self.assertTrue(report.achieved)
        self.assertEqual(report.confirmed, 1)
        self.assertEqual(browser.confirmed, 1)

    def test_does_not_confirm_without_success(self):
        responses = [SubmissionResult(dom_text="I'm sorry, I can't help.")]
        gen, browser = self._make(responses)
        report = gen.run("https://target/", budget=1)
        self.assertFalse(report.achieved)
        self.assertEqual(report.confirmed, 0)

    def test_budget_caps_submissions(self):
        # All refusals; budget=3 must cap total submissions.
        refusals = [SubmissionResult(dom_text="I'm sorry, no.") for _ in range(20)]
        gen, _ = self._make(refusals)
        report = gen.run("https://target/", budget=3)
        self.assertFalse(report.achieved)
        self.assertLessEqual(report.submissions, 3)

    def test_records_best_score(self):
        responses = [
            SubmissionResult(dom_text="Step 1 technical detail"),  # B ~65
            SubmissionResult(dom_text="nope"),                     # C
        ]
        gen, _ = self._make(responses)
        report = gen.run("https://target/", budget=2)
        self.assertIsNotNone(report.best)
        self.assertGreater(report.best.score, 0)

    def test_opens_url_once(self):
        responses = [SubmissionResult(dom_text="HTB{x}")]
        gen, browser = self._make(responses)
        gen.run("https://target/")
        self.assertEqual(browser.opened_urls, ["https://target/"])


class TestFacade(unittest.TestCase):
    def test_build_engine_with_defaults(self):
        obj = Objective(track=Track.OFFICE, goal="x")
        gen = build_engine(obj)
        self.assertIsInstance(gen, Generator)
        # Default browser is the dry-run client.
        from jb_ape.browser import DryRunBrowserClient
        self.assertIsInstance(gen.browser, DryRunBrowserClient)

    def test_quick_run_smoke(self):
        from jb_ape.facade import quick_run
        from jb_ape.generator import RunConfig

        obj = Objective(
            track=Track.CODING, goal="flag",
            success_patterns=[r"HTB\{.*?\}"],
        )
        browser = DryRunBrowserClient(
            responses=[SubmissionResult(dom_text="HTB{quick}")]
        )
        # run_recon=False isolates the attack loop (recon tested in test_recon).
        report = quick_run(
            obj, "https://x/", browser=browser, budget=5,
            config=RunConfig(run_recon=False),
        )
        self.assertIsInstance(report, RunReport)
        self.assertTrue(report.achieved)


if __name__ == "__main__":
    unittest.main()
