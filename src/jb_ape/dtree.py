"""Decision-tree test-case generator — the methodology core (devdocs/16).

Reframes the engine from "flat planner loop" to an explicit **decision tree**,
per the project direction: the harness (execution: browser/targets/judge) is
secondary; the key is a paper-grade synthesis of ALL fused knowledge
(devdocs/02 §6, 03, 05, 07, 11, 13, 14, 15) that **continuously emits test
cases** — the tree walks from *observations* (recon profile, judge feedback,
Wei failure-mode) through *decisions* to *leaf generators* that compose
technique × bypass × overlay into fresh cases.

Formal sketch (devdocs/16):
  TargetState  σ = ⟨track, layers ⊆ {L1,L2,L3,L1out}, ppl_filter,
                      agent_surface, model_family, last_blocked_mode⟩
  Tree         T = nodes; internal nodes ask a predicate over σ;
               leaves λ(families, overlay_policy, bypass_policy) EMIT cases.
  Walker       best-first over the untried frontier, scored by bandit priors
               of the leaf's technique family; dedup by payload hash;
  Update       record(case, verdict): success → path solved; ≥3 failures →
               prune (unless high prior); last_blocked_mode re-routes the
               failure-mode branch. Supply is UNBOUNDED: when depth-1 leaves
               are exhausted the walker DEEPENS (overlay combos, scenario
               nesting, crossover of top survivors).

Offline-hermetic: no LLM required for traversal/emission (mechanical
composers only); integrates with Generator via the planner duck-interface
(``plan_round``) and consumes the existing signal contracts (profile,
last_blocked_mode) set by the generator.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from jb_ape.defense import variant_bundle
from jb_ape.jailbreak import (
    WEI_COMBINATIONS,
    FailureMode,
    combine_overlays,
    technique_failure_mode,
)
from jb_ape.models import DefenseLayer, Objective, Track, Variant
from jb_ape.scenarios import CODE, STORY, nest
from jb_ape.techniques import TECHNIQUES, render

# ─────────────────────────────── target state ─────────────────────────────────


@dataclass
class TargetState:
    """Everything the tree observes about the target (updated by feedback)."""

    track: Track = Track.OFFICE
    layers: set = field(default_factory=set)          # set[DefenseLayer]
    ppl_filter: bool = False
    agent_surface: bool = True                         # tools/skills present?
    model_family: str | None = None
    last_blocked_mode: FailureMode | None = None
    hints: list = field(default_factory=list)          # operator steering (devdocs/17)
    disabled_families: set = field(default_factory=set)  # structural steer: blocked T-*

    @classmethod
    def from_profile(cls, profile, track: Track) -> TargetState:
        if profile is None:
            return cls(track=track)
        return cls(
            track=track,
            layers=set(profile.detected_layers),
            ppl_filter=bool(getattr(profile, "ppl_filter_active", False)),
            agent_surface=bool(getattr(profile, "agent_tools", [])) or True,
            model_family=None,
        )

    def with_blocked_mode(self, mode: FailureMode | None) -> TargetState:
        self.last_blocked_mode = mode
        return self


# ─────────────────────────────── leaf generators ──────────────────────────────

INPUT_BYPASSES = ["B-I3", "B-I2", "B-I1"]        # devdocs/03 §2 order
OUTPUT_BYPASSES = ["B-O1", "B-O2", "B-O4", "B-O3"]
OVERLAY_COMBO_1 = WEI_COMBINATIONS["combo_1"]      # prefix + refusal-suppression
OVERLAY_COMBO_2 = WEI_COMBINATIONS["combo_2"]

_HIGH_PPL = {"B-I2", "B-I5"}


@dataclass
class Leaf:
    """A leaf that emits one composed test case per call."""

    lid: str                       # stable leaf id = decision path
    families: list[str]            # technique ids (T-*) prioritized
    bypasses: list[str]            # mechanical bypasses to apply in order
    overlays: list[str]            # J-overlay combo (may be empty)
    nest_scenario: str | None = None  # "S-CODE" | "S-STORY" | None
    problem: str = "generic"

    def emit(self, goal: str, state: TargetState, seed_pool: list[str] | None = None,
             depth: int = 0) -> Variant:
        """Compose one fresh test case. Mechanical only (zero-LLM).

        Depth is the walker's unbounded novelty axis (devdocs/16 §4) — the
        composition space is CYCLIC in depth: bypass prefix-set rotates,
        overlay tier cycles combo_1→2→3, nesting alternates — so greater
        traversal depth always yields a NEW payload and the walker never
        starves under dedup."""
        d = depth
        # 1. base body: technique render, or a curated seed at depth 0.
        body = None
        chain: list[str] = []
        if seed_pool and d == 0:
            body = seed_pool[0]
            chain.append("SEED")
        # primary technique ROTATES with depth — doubles the composition space
        fam = self.families[d % len(self.families)] if self.families else None
        tech = TECHNIQUES.get(fam)
        if body is None:
            body = render(tech, goal) if tech else goal
            chain.append(tech.tid if tech else "RAW")
        targets = {"steal", "password", "secret", "key", "credential",
                   "refund", "hack", "exploit", "admin"}
        # 2. bypasses — rotate the applied prefix-set with depth.
        n_b = len(self.bypasses)
        take = self.bypasses[: (d % n_b) + 1] if n_b else []
        applied: list[str] = []
        for bid in take:
            if state.ppl_filter and bid in _HIGH_PPL:
                continue
            got = variant_bundle(body, bid, targets=targets, k=1)
            if got:
                body = got[0]
                applied.append(bid)
        chain.extend(applied)
        # 3. overlays — cycle [native|combo_1, combo_2, combo_3] with depth.
        if d >= 1:
            pool = [list(self.overlays) or list(OVERLAY_COMBO_1),
                    list(OVERLAY_COMBO_2), list(WEI_COMBINATIONS["combo_3"])]
            chosen_ov = pool[(d - 1) % 3]
        else:
            chosen_ov = list(self.overlays)
        if chosen_ov:
            body = combine_overlays(body, chosen_ov, targets=targets)
            chain.append("OV:" + "+".join(chosen_ov))
        # 4. nesting — leaf-native alternates; bare leaves gain it at d>=2.
        if self.nest_scenario:
            nest_mode = (self.nest_scenario if d % 2 == 0
                         else ("S-CODE" if self.nest_scenario != "S-CODE" else "S-STORY"))
        elif d >= 2:
            nest_mode = ("S-CODE", "S-STORY")[d % 2]
        else:
            nest_mode = None
        if nest_mode == "S-CODE":
            body = nest(CODE, body)
            chain.append("S-CODE")
        elif nest_mode == "S-STORY":
            body = nest(STORY, body)
            chain.append("S-STORY")
        # Operator steering (devdocs/17 §2): the outer agent's hint rides as a
        # bracketed context line on every subsequent emission — observable,
        # testable, and honestly documented (this IS the steer semantics).
        if getattr(state, "hints", None):
            body += "\n[operator context] " + str(state.hints[-1])
            chain.append("STEER")
        return Variant(payload=body, technique=(tech.tid if tech else "RAW"),
                       scenario=nest_mode or "",
                       bypasses=[b for b in self.bypasses
                                 if not (state.ppl_filter and b in _HIGH_PPL)],
                       mutation_chain=[self.lid] + chain, depth=d)


# ─────────────────────────────── the knowledge tree ───────────────────────────
# Structure = the methodology; routing predicates over TargetState.

def build_leaves() -> list[Leaf]:
    """All leaves, grouped by the problem class each solves (devdocs/16 §3)."""
    ls: list[Leaf] = []

    # Class A — agent-abuse surface (hijack/exfil/workflow/supply-chain).
    ls += [
        Leaf("A.hijack.direct", ["T-D3", "T-D1"], [], OVERLAY_COMBO_1,
             problem="tool-hijack"),
        Leaf("A.hijack.nest", ["T-B2", "T-B4"], [], [], nest_scenario="S-CODE",
             problem="tool-hijack"),
        Leaf("A.exfil.charsplit", ["T-A3"], ["B-O1"], [],
             problem="exfiltration"),
        Leaf("A.exfil.callback", ["T-A3"], ["B-O4"], [],
             problem="exfiltration"),
        Leaf("A.workflow.f1", ["T-F1"], [], [],
             problem="workflow-assembly"),
        Leaf("A.workflow.f2", ["T-F2"], [], [],
             problem="workflow-assembly"),
        Leaf("A.trace.f4", ["T-F4"], [], OVERLAY_COMBO_1,
             problem="indirect-injection"),
        Leaf("A.entity.f3", ["T-F3"], [], [],
             problem="indirect-injection"),
        Leaf("A.supply.skill", ["T-C1"], [], [],
             problem="skill-poisoning"),
        Leaf("A.spread.subagent", ["T-C1"], [], OVERLAY_COMBO_2,
             problem="multi-agent-spread"),
        Leaf("A.overeager.snare", ["T-D1"], [], [],
             problem="overeager"),
        Leaf("A.idor.b5", ["T-C1", "T-D1"], ["B-I3"], [],
             problem="idor-privilege"),
    ]
    # Class B — content jailbreak (leak / forbidden generation).
    ls += [
        Leaf("B.leak.override", ["T-C1", "T-B2"], [], OVERLAY_COMBO_1,
             problem="direct-jailbreak"),
        Leaf("B.leak.sop", ["T-D1", "T-D3"], [], [],
             problem="direct-jailbreak"),
        Leaf("B.codegen.nest", ["T-A1", "T-A3"], [], [],
             nest_scenario="S-CODE", problem="direct-jailbreak"),
        Leaf("B.codegen.story", ["T-A3"], [], [], nest_scenario="S-STORY",
             problem="direct-jailbreak"),
    ]
    # Conditioning leaves (applied when the state says a layer is active).
    ls += [
        Leaf("X.l1.synonym", ["T-A3", "T-D1"], ["B-I3"], [],
             problem="condition:L1"),
        Leaf("X.l1.encode", ["T-D1"], ["B-I2"], [],
             problem="condition:L1"),
        Leaf("X.l1out.split", ["T-A3", "T-B2"], ["B-O1"], [],
             problem="condition:L1out"),
        Leaf("X.l2.tunnel", ["T-E1", "T-C1"], [], OVERLAY_COMBO_2,
             problem="condition:L2"),
        Leaf("X.l3.mismatched", ["T-A3", "T-D1"], ["B-I2"], [],
             nest_scenario="S-STORY", problem="condition:L3-mismatched"),
    ]
    return ls


PROBLEM_FOR_LEAF = {lf.lid: lf.problem for lf in build_leaves()}


def route(state: TargetState, leaves: list[Leaf]) -> list[Leaf]:
    """The routing predicates: which leaves are live under this state.

    Implements the decision tree's internal nodes (devdocs/16 §2):
      class split (agent-abuse vs content) → defense conditions →
      failure-mode rotation → PPL constraint.
    """
    live: list[Leaf] = []
    for leaf in leaves:
        if state.disabled_families and any(
                f in state.disabled_families for f in leaf.families):
            continue  # structurally disabled by the operator (devdocs/17 §4)
        p = leaf.problem
        if p.startswith("condition:"):
            cond = p.split(":", 1)[1]
            if cond == "L1" and DefenseLayer.L1 not in state.layers:
                continue
            if cond == "L1out" and DefenseLayer.L1_OUT not in state.layers:
                continue
            if cond == "L2" and DefenseLayer.L2 not in state.layers:
                continue
            if cond == "L3-mismatched":
                # live only when the last blocked mode was COMPETING
                # (Wei rotation: same-mode repetition is pointless).
                if state.last_blocked_mode is not FailureMode.COMPETING:
                    continue
                if state.ppl_filter and "B-I2" in leaf.bypasses:
                    continue
            live.append(leaf)
            continue
        # class split
        if p in ("tool-hijack", "exfiltration", "workflow-assembly",
                 "skill-poisoning", "multi-agent-spread", "overeager",
                 "indirect-injection", "idor-privilege") and not state.agent_surface:
            continue
        live.append(leaf)
    # PPL constraint globally demotes (leaf.emit already skips high-PPL bypass).
    return live


# ─────────────────────────────── the walker ───────────────────────────────────


@dataclass
class _LeafStat:
    tried: int = 0
    wins: int = 0
    fails: int = 0
    solved: bool = False
    pruned: bool = False


class TreeWalker:
    """Best-first traversal that continuously emits distinct test cases."""

    def __init__(self, objective: Objective, bandit=None) -> None:
        self.objective = objective
        self.bandit = bandit
        self.state = TargetState(track=objective.track)
        self.leaves = build_leaves()
        self.stats: dict[str, _LeafStat] = {lf.lid: _LeafStat() for lf in self.leaves}
        self._emitted_hashes: set[str] = set()
        self._all_cases: list[Variant] = []   # crossover pool (unbounded supply)
        self._xover_cursor = 0
        self._depth = 0
        self.solved_paths: list[str] = []

    # The generator writes the round's majority blocked mode to
    # ``planner.last_blocked_mode`` (planner.Planner has it as a real field);
    # route() reads it off TargetState. Proxy both ways so the one signal
    # can't land on an attribute nobody reads.
    @property
    def last_blocked_mode(self) -> FailureMode | None:
        return self.state.last_blocked_mode

    @last_blocked_mode.setter
    def last_blocked_mode(self, mode: FailureMode | None) -> None:
        self.state.last_blocked_mode = mode

    # -- scoring --------------------------------------------------------------
    def _score(self, leaf: Leaf) -> float:
        st = self.stats[leaf.lid]
        if st.solved or st.pruned:
            return -1.0
        prior = 1.0
        if self.bandit is not None:
            # mean of the Beta posterior on the leaf's primary technique.
            arm = self.bandit.arm(self.objective.track, leaf.families[0])
            prior = (arm.alpha / (arm.alpha + arm.beta)) if (arm.alpha + arm.beta) else 0.5
        # untried leaves first (novelty), then prior-weighted.
        return (1.0 if st.tried == 0 else 0.0) + prior - 0.1 * st.fails

    # -- emission ---------------------------------------------------------------
    def next_cases(self, k: int = 3, seed_pool: list[str] | None = None) -> list[Variant]:
        """Emit up to k DISTINCT cases (dedup by payload hash). Never starves:
        depth-offset attempts + cyclic composition space (see Leaf.emit)."""
        live = [leaf for leaf in route(self.state, self.leaves)
                if self._score(leaf) >= 0]
        live.sort(key=self._score, reverse=True)
        out: list[Variant] = []
        for leaf in live:
            for attempt in range(3):  # depth-offset attempts → fresh variants
                # every ATTEMPT counts toward exhaustion, else dedup blocks
                # the tried-counter and the walker starves (found by test).
                self.stats[leaf.lid].tried += 1
                v = leaf.emit(self.objective.goal, self.state,
                              seed_pool=seed_pool, depth=self._depth + attempt)
                h = hashlib.sha1(v.payload.strip().lower().encode()).hexdigest()[:12]
                if h not in self._emitted_hashes:
                    self._emitted_hashes.add(h)
                    out.append(v)
                    break  # one fresh case per leaf per call
                if len(out) >= k:
                    break
            if len(out) >= k:
                break
        self._maybe_deepen(live)
        # Crossover fallback — the UNBOUNDED-supply guarantee: when the
        # mechanical composition space is exhausted (all hashes seen), merge
        # two previously-emitted cases (GPTFuzzer CrossOver, devdocs/12 §4.1;
        # pair-space grows with every emission → never starves).
        while len(out) < k and len(self._all_cases) >= 2:
            i = self._xover_cursor % len(self._all_cases)
            j = (i + 1 + (self._xover_cursor // len(self._all_cases))) % len(self._all_cases)
            self._xover_cursor += 1
            if i == j:
                continue
            a, b = self._all_cases[i], self._all_cases[j]
            body = a.payload + "\n" + b.payload
            h = hashlib.sha1(body.strip().lower().encode()).hexdigest()[:12]
            if h in self._emitted_hashes:
                if self._xover_cursor > 4 * len(self._all_cases) ** 2:
                    break  # bounded search; practically unreachable
                continue
            self._emitted_hashes.add(h)
            out.append(Variant(
                payload=body, technique=a.technique,
                scenario=a.scenario,
                bypasses=list(dict.fromkeys(a.bypasses + b.bypasses)),
                mutation_chain=["XOVER", a.mutation_chain[0] if a.mutation_chain else "?",
                                b.mutation_chain[0] if b.mutation_chain else "?"],
                depth=max(a.depth, b.depth) + 1))
        self._all_cases.extend(out)
        return out

    def _maybe_deepen(self, live: list) -> None:
        """Advance traversal depth once every live leaf is exhausted at the
        current depth; re-arms their tried counters (unbounded supply)."""
        if live and all(self.stats[lf.lid].tried >= 1 for lf in live):
            self._depth += 1
            for lf in live:  # allow re-emission per leaf at the new depth
                self.stats[lf.lid].tried = 0

    # -- feedback ----------------------------------------------------------------
    def record(self, variant: Variant, achieved: bool, score: int) -> None:
        lid = variant.mutation_chain[0] if variant.mutation_chain else ""
        st = self.stats.get(lid)
        if st is None:
            return
        if achieved:
            st.wins += 1
            st.solved = True
            self.solved_paths.append(lid)
        else:
            st.fails += 1
            if st.fails >= 3:
                st.pruned = True
        # Wei rotation: propagate the blocked failure mode into routing.
        tech = variant.technique
        if not achieved and tech in TECHNIQUES:
            self.state.with_blocked_mode(technique_failure_mode(tech))

    # -- planner duck-interface (Generator integration) --------------------------
    def plan_round(self, round_idx: int, max_rounds: int,
                   bundle_size: int = 3) -> list[Variant]:
        if round_idx == 0:
            pass  # placeholder; seeds come from armory via generator
        return self.next_cases(k=bundle_size, seed_pool=None)


def render_tree() -> str:
    """ASCII rendering of the methodology tree (paper figure / debugging)."""
    lines = ["ROOT (objective, recon profile)",
             "├─ Class A: agent-abuse surface (tools/skills present)"]
    a = [lf for lf in build_leaves() if not lf.problem.startswith("condition:")
         and not lf.problem.startswith("B.")]
    for lf in a:
        lines.append(f"│   ├─ {lf.lid:<22} → {', '.join(lf.families)}"
                     f"{' +' + '+'.join(lf.bypasses) if lf.bypasses else ''}"
                     f"{' ⊕' + '+'.join(lf.overlays) if lf.overlays else ''}")
    lines.append("├─ Class B: content jailbreak")
    for lf in build_leaves():
        if lf.lid.startswith("B."):
            lines.append(f"│   ├─ {lf.lid:<22} → {', '.join(lf.families)}")
    lines.append("└─ X: defense-conditioned (live only when state says so)")
    for lf in build_leaves():
        if lf.problem.startswith("condition:"):
            lines.append(f"    ├─ {lf.lid:<22} when {lf.problem.split(':', 1)[1]}"
                         f" → {', '.join(lf.families)}{' +' + '+'.join(lf.bypasses) if lf.bypasses else ''}")
    lines.append("")
    lines.append("Traversal: best-first (novelty + bandit prior − fails); "
                 "dedup by payload hash; ≥3 fails → prune; success → solved;")
    lines.append("supply unbounded: depth 0→3 (overlay stacking + nesting + "
                 "crossover via rewriter when embedded in Generator).")
    return "\n".join(lines)
