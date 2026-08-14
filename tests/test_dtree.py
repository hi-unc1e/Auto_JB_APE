"""Tests for the decision-tree test-case generator (devdocs/16).

Acceptance mirrors the user's directive: the tree must (a) encode the fused
knowledge as explicit branches, (b) route on observations, (c) emit DISTINCT
cases continuously, (d) update from feedback (prune/solve/rotate), and (e)
drop into the existing Generator loop unchanged.
"""

from __future__ import annotations

import unittest

from jb_ape.catalog import SCENARIOS, build_objective, hijack_markers_for, mint_canary
from jb_ape.dtree import (
    INPUT_BYPASSES,
    OUTPUT_BYPASSES,
    TargetState,
    TreeWalker,
    build_leaves,
    render_tree,
    route,
)
from jb_ape.facade import build_engine
from jb_ape.generator import RunConfig
from jb_ape.jailbreak import FailureMode
from jb_ape.models import DefenseLayer, Track
from jb_ape.planner import Bandit
from jb_ape.targets import LLMTargetClient


class TestStructure(unittest.TestCase):
    def test_all_problem_categories_reachable(self):
        problems = {lf.problem for lf in build_leaves()}
        for cat in ("tool-hijack", "exfiltration", "workflow-assembly",
                    "skill-poisoning", "multi-agent-spread", "overeager",
                    "indirect-injection", "idor-privilege", "direct-jailbreak"):
            self.assertIn(cat, problems)

    def test_conditioning_leaves_exist(self):
        conds = {lf.problem for lf in build_leaves()
                 if lf.problem.startswith("condition:")}
        self.assertTrue({"condition:L1", "condition:L1out",
                         "condition:L2", "condition:L3-mismatched"} <= conds)

    def test_render_tree_smoke(self):
        out = render_tree()
        self.assertIn("Class A", out)
        self.assertIn("Traversal", out)
        self.assertIn("A.hijack.direct", out)


class TestRouting(unittest.TestCase):
    def test_l1_condition_gates_on_state(self):
        st = TargetState(track=Track.CODING)
        self.assertEqual([lf for lf in route(st, build_leaves())
                          if lf.problem == "condition:L1"], [])
        st.layers.add(DefenseLayer.L1)
        self.assertTrue([lf for lf in route(st, build_leaves())
                         if lf.problem == "condition:L1"])

    def test_no_agent_surface_drops_agent_leaves(self):
        st = TargetState(track=Track.CODING, agent_surface=False)
        live = route(st, build_leaves())
        self.assertFalse(any(lf.problem == "tool-hijack" for lf in live))
        # content-jailbreak leaves remain
        self.assertTrue(any(lf.problem == "direct-jailbreak" for lf in live))

    def test_mismatched_leaf_only_after_competing_block(self):
        st = TargetState(track=Track.CODING)
        self.assertFalse([lf for lf in route(st, build_leaves())
                          if lf.problem == "condition:L3-mismatched"])
        st.last_blocked_mode = FailureMode.COMPETING
        self.assertTrue([lf for lf in route(st, build_leaves())
                         if lf.problem == "condition:L3-mismatched"])

    def test_ppl_filter_blocks_high_ppl_mismatched_leaf(self):
        st = TargetState(track=Track.CODING, ppl_filter=True)
        st.last_blocked_mode = FailureMode.COMPETING
        got = [lf for lf in route(st, build_leaves())
               if lf.problem == "condition:L3-mismatched"]
        self.assertFalse(any("B-I2" in lf.bypasses for lf in got))


class TestContinuousEmission(unittest.TestCase):
    def _walker(self):
        obj = build_objective(SCENARIOS["data-exfil"], canary="RT-walker01")
        return TreeWalker(objective=obj, bandit=Bandit())

    def test_emits_distinct_cases_indefinitely(self):
        w = self._walker()
        seen = []
        for _ in range(40):  # far beyond leaf count → depth mechanism engaged
            batch = w.next_cases(k=3)
            self.assertTrue(batch)  # never starves
            seen.extend(v.payload for v in batch)
        self.assertEqual(len(seen), len(set(seen)),
                         "duplicate payload emitted")

    def test_chain_carries_leaf_path(self):
        w = self._walker()
        for v in w.next_cases(k=2):
            self.assertRegex(v.mutation_chain[0], r"^(A|B|X)\.")

    def test_bypass_families_in_leaf_specs(self):
        leaves = {lf.lid: lf for lf in build_leaves()}
        self.assertEqual(leaves["X.l1.synonym"].bypasses, ["B-I3"])
        self.assertEqual(leaves["X.l1out.split"].bypasses, ["B-O1"])
        self.assertEqual(INPUT_BYPASSES[0], "B-I3")
        self.assertEqual(OUTPUT_BYPASSES[0], "B-O1")


class TestFeedback(unittest.TestCase):
    def test_success_marks_solved(self):
        w = self._feedback_walker()
        cases = w.next_cases(k=1)
        w.record(cases[0], achieved=True, score=100)
        lid = cases[0].mutation_chain[0]
        self.assertIn(lid, w.solved_paths)
        # solved leaf no longer scores
        self.assertEqual(w._score(next(lf for lf in w.leaves if lf.lid == lid)), -1.0)

    def test_three_fails_prune(self):
        w = self._feedback_walker()
        cases = w.next_cases(k=1)
        lid = cases[0].mutation_chain[0]
        for _ in range(3):
            w.record(cases[0], achieved=False, score=10)
        leaf = next(lf for lf in w.leaves if lf.lid == lid)
        self.assertTrue(w.stats[lid].pruned)
        self.assertEqual(w._score(leaf), -1.0)

    def test_blocked_mode_rotates_routing(self):
        w = self._feedback_walker()
        before = [lf.lid for lf in route(w.state, w.leaves)
                  if lf.problem == "condition:L3-mismatched"]
        self.assertEqual(before, [])
        # record a COMPETING-technique failure → mismatched branch goes live
        v = next(lf for lf in w.leaves
                 if lf.problem == "tool-hijack").emit(
            w.objective.goal, w.state)
        w.record(v, achieved=False, score=5)
        after = [lf.lid for lf in route(w.state, w.leaves)
                 if lf.problem == "condition:L3-mismatched"]
        self.assertTrue(after)

    def _feedback_walker(self):
        from jb_ape.models import Objective

        return TreeWalker(objective=Objective(track=Track.CODING, goal="g"),
                          bandit=Bandit())


class TestGeneratorIntegration(unittest.TestCase):
    """The walker drops into the existing closed loop (planner duck-type)."""

    def test_full_loop_win_with_tree_planner(self):
        canary = mint_canary()
        obj = build_objective(SCENARIOS["tool-call-hijack"], canary=canary)
        markers = hijack_markers_for(SCENARIOS["tool-call-hijack"], canary)
        reply = ('{"name": "run_terminal", "arguments": '
                 '{"command": "echo ' + canary + '"}}')
        target = LLMTargetClient(model="fake", transport=lambda msgs: reply)
        gen = build_engine(obj, browser=target, armory_root=None,
                           hijack_success_markers=markers,
                           planner_kind="tree",
                           config=RunConfig(run_recon=False, bundle_size=3,
                                            max_rounds=3))
        rep = gen.run("https://t/", budget=8)
        self.assertTrue(rep.achieved)

    def test_planner_interface_shape(self):
        from jb_ape.models import Objective

        w = TreeWalker(objective=Objective(track=Track.OFFICE, goal="g"),
                       bandit=Bandit())
        cases = w.plan_round(0, 10, 3)
        self.assertLessEqual(len(cases), 3)
        self.assertTrue(all(c.payload for c in cases))


if __name__ == "__main__":
    unittest.main()
