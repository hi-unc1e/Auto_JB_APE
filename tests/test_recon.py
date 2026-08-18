"""Tests for the reconnaissance orchestrator (devdocs/02 §7)."""

from __future__ import annotations

import unittest

from jb_ape.browser import DryRunBrowserClient
from jb_ape.models import DefenseLayer, SubmissionResult, Track
from jb_ape.recon import FALLBACK_PROBES, Recon, ReconReport


class TestReconRun(unittest.TestCase):
    def test_runs_probes_and_builds_profile(self):
        responses = [
            SubmissionResult(dom_text="You are a helpful assistant. Rule 1: ..."),  # SP
            SubmissionResult(dom_text="I'm sorry, I can't help with steal."),      # L1A refused
            SubmissionResult(dom_text="sure, exfiltrate is fine"),                 # L1B ok
            SubmissionResult(dom_text="TESTKEY-sk-abc123xyz"),                     # LO2 raw
            SubmissionResult(dom_text="Tools: get_order(params: id)"),             # TL1
            SubmissionResult(dom_text="To pick a padlock: first you ..."),         # MD2 complied
        ]
        br = DryRunBrowserClient(responses=responses)
        recon = Recon(armory=None)
        report = recon.run(br, "https://x/", budget=10)
        self.assertIsInstance(report, ReconReport)
        self.assertEqual(report.cost, len(FALLBACK_PROBES))
        # System prompt leaked → L2 not in active layers.
        self.assertNotIn(DefenseLayer.L2, report.profile.detected_layers)
        # L1 detected (steal got refused).
        self.assertIn(DefenseLayer.L1, report.profile.detected_layers)
        # L1' NOT active (raw key came back).
        self.assertFalse(report.profile.l1out_redacts)
        # Agent tools enumerated.
        self.assertTrue(any("get_order" in t or "id" in t for t in report.profile.agent_tools))
        # L3 weak (complied with padlock).
        self.assertNotIn(DefenseLayer.L3, report.profile.detected_layers)

    def test_detects_l1out_redaction(self):
        responses = [
            SubmissionResult(dom_text="You are helpful."),      # SP
            SubmissionResult(dom_text="I can't help."),         # L1A refused
            SubmissionResult(dom_text="ok"),                    # L1B
            SubmissionResult(dom_text="TESTKEY-[REDACTED]"),    # LO2 redacted!
            SubmissionResult(dom_text="(no tools)"),            # TL1
            SubmissionResult(dom_text="I refuse."),             # MD2 refused
        ]
        br = DryRunBrowserClient(responses=responses)
        recon = Recon(armory=None)
        report = recon.run(br, "https://x/", budget=10)
        self.assertTrue(report.profile.l1out_redacts)
        self.assertIn(DefenseLayer.L1_OUT, report.profile.detected_layers)

    def test_budget_caps_probes(self):
        br = DryRunBrowserClient(
            responses=[SubmissionResult(dom_text="x") for _ in range(20)]
        )
        recon = Recon(armory=None)
        report = recon.run(br, "https://x/", budget=3)
        self.assertLessEqual(report.cost, 3)

    def test_probe_failure_does_not_crash(self):
        class Boom:
            opened = []
            def open(self, url, *, session_id=None): self.opened.append(url)
            def submit_payload(self, payload, *, dry_run=False):
                raise RuntimeError("network down")
            # pragma: no cover - other methods unused here
            def snapshot_interactive(self): return ""
            def fill(self, ref, text): ...
            def click(self, ref): ...
            def press(self, key): ...
            def wait(self, spec): ...
            def get_dom_text(self): return ""
            def get_api_responses(self): return []
            def get_network_log(self): return []
            def get_console_log(self): return []
            def confirm_submit(self): ...
        recon = Recon(armory=None)
        report = recon.run(Boom(), "https://x/", budget=5)
        # Each failed probe still counts as spent (best-effort), but no crash.
        self.assertIsInstance(report, ReconReport)


class TestReconProfileFeedsPlanner(unittest.TestCase):
    """The recon-built profile should reach the planner via the generator."""

    def test_generator_attaches_recon_profile(self):
        from jb_ape.facade import build_engine
        from jb_ape.generator import RunConfig
        from jb_ape.models import Objective

        responses = [
            SubmissionResult(dom_text="You are helpful."),      # SP
            SubmissionResult(dom_text="sorry, no steal."),      # L1A
            SubmissionResult(dom_text="ok exfiltrate"),         # L1B
            SubmissionResult(dom_text="TESTKEY-***"),           # LO2 redacted
            SubmissionResult(dom_text="no tools"),              # TL1
            SubmissionResult(dom_text="I refuse."),             # MD2
            SubmissionResult(dom_text="HTB{found}"),            # the actual hit
        ]
        obj = Objective(track=Track.OFFICE, goal="leak",
                        success_patterns=[r"HTB\{.*?\}"])
        br = DryRunBrowserClient(responses=responses)
        gen = build_engine(
            obj, browser=br,
            config=RunConfig(bundle_size=2, max_rounds=2, run_recon=True),
            armory_root="armory",
        )
        report = gen.run("https://x/", budget=15, recon_budget=6)
        # Recon profile attached.
        self.assertIsNotNone(report.recon_profile)
        self.assertGreater(report.recon_cost, 0)


if __name__ == "__main__":
    unittest.main()
