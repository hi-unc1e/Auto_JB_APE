"""Planner — technique selection via contextual bandit + tree search
(devdocs/05 §5, §6).

Two concerns:

* ``Bandit`` — Thompson-sampling contextual bandit keyed by ``(track, arm)``.
  Rewards come from the judge. ``arm`` is a coarse strategy id combining a
  technique id with the primary bypass it applied (devdocs/05 §5.3).
* ``Planner`` — picks arms via the bandit, renders seed variants, and exposes a
  tree-search step (``prune``) so the generator can drop low-scoring branches
  (TAP-style, devdocs/05 §6.1).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from jb_ape.models import DefenseProfile, Objective, Track, Variant
from jb_ape.techniques import TECHNIQUES, Technique, render, technique_for_track


@dataclass
class BanditArm:
    """Beta(α, β) posterior for one strategy arm (devdocs/05 §5.2)."""

    arm_id: str
    alpha: float = 1.0
    beta: float = 1.0

    def update(self, reward: float) -> None:
        """reward in [0,1]; ≥0.5 → success-like, else failure-like."""
        if reward >= 0.5:
            self.alpha += 2.0 * (reward - 0.5) * 2  # scale to strengthen signal
        else:
            self.beta += 2.0 * (0.5 - reward) * 2

    def sample(self, rng: random.Random) -> float:
        return rng.betavariate(max(0.01, self.alpha), max(0.01, self.beta))


class Bandit:
    """Contextual Thompson bandit (devdocs/05 §5.3). State is independent per
    track so an office-track win doesn't distort ecommerce choices."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self._arms: dict[tuple[Track, str], BanditArm] = {}

    def arm(self, track: Track, arm_id: str) -> BanditArm:
        key = (track, arm_id)
        if key not in self._arms:
            self._arms[key] = BanditArm(arm_id=arm_id)
        return self._arms[key]

    def select(self, track: Track, arm_ids: list[str], explore_eps: float = 0.2) -> str:
        """Thompson-select an arm. With probability ``explore_eps`` pick uniformly
        (ε-greedy exploration on top of Thompson for cold-start diversity)."""
        if not arm_ids:
            raise ValueError("arm_ids must be non-empty")
        if self.rng.random() < explore_eps:
            return self.rng.choice(arm_ids)
        best, best_s = None, -1.0
        for aid in arm_ids:
            s = self.arm(track, aid).sample(self.rng)
            if s > best_s:
                best, best_s = aid, s
        return best  # type: ignore[return-value]

    def reward(self, track: Track, arm_id: str, achieved: bool, score: int) -> None:
        """Convert a judge verdict into a [0,1] reward and update the posterior."""
        norm = max(0.0, min(1.0, score / 100.0))
        # Bonus for achieving the objective (devdocs/05 §5.2).
        reward = min(1.0, norm + (0.25 if achieved else 0.0))
        self.arm(track, arm_id).update(reward)

    def prime(self, track: Track, priors: dict[str, tuple[float, float]]) -> None:
        """Warm-start posteriors from literature priors (armory/priors).
        Merges the prior (α, β) into the existing Beta posterior so the bandit
        isn't blind on the first round of a new track."""
        for arm_id, (alpha, beta) in priors.items():
            arm = self.arm(track, arm_id)
            arm.alpha += max(0.0, alpha - 1.0)
            arm.beta += max(0.0, beta - 1.0)


@dataclass
class Planner:
    """Selects techniques and seeds initial variants each round.

    When an ``Armory`` is attached, the planner:
    1. warm-starts the bandit from literature priors (prime on first round),
    2. seeds each round from curated track seeds + technique renders,
    3. prioritizes validated effective chains for the track.
    """

    objective: Objective
    bandit: Bandit
    profile: DefenseProfile | None = None
    armory: object | None = None  # jb_ape.armory.Armory (typed loosely to avoid import cycle)
    explore_eps_start: float = 0.3
    explore_eps_end: float = 0.05
    # Wei failure-mode feedback (devdocs/14 §1): set by the generator after a
    # round was blocked — plan_round then prefers the OPPOSITE mode's techniques.
    last_blocked_mode: object | None = None  # jailbreak.FailureMode | None
    # Operator steering (devdocs/17 §4) — the same two signals TargetState
    # carries for the tree planner, so Engagement.steer works on BOTH:
    # hints ride as a bracketed [operator context] line on every seed;
    # disabled families are removed from the candidate pool.
    hints: list[str] = field(default_factory=list)
    disabled_families: set[str] = field(default_factory=set)

    def _candidate_techniques(self) -> list[Technique]:
        techs = technique_for_track(self.objective.track)
        techs = techs or list(TECHNIQUES.values())
        if self.disabled_families:
            kept = [t for t in techs if t.tid not in self.disabled_families]
            # Disabling the entire pool is an operator error — fall back to
            # the full pool rather than starving plan_round.
            techs = kept or techs
        return techs

    def _eps(self, round_idx: int, max_rounds: int) -> float:
        if max_rounds <= 1:
            return self.explore_eps_end
        t = max(0.0, min(1.0, round_idx / max(1, max_rounds - 1)))
        return self.explore_eps_start + t * (self.explore_eps_end - self.explore_eps_start)

    def plan_round(
        self,
        round_idx: int,
        max_rounds: int,
        bundle_size: int = 3,
    ) -> list[Variant]:
        """Pick a technique via the bandit and render ``bundle_size`` seed
        variants going shallow → deep. The generator/rewriter extends these."""
        # Warm-start the bandit once from literature priors (devdocs/05 §5.2).
        if round_idx == 0 and self.armory is not None:
            priors = self.armory.load_priors(self.objective.track)
            if priors:
                self.bandit.prime(self.objective.track, priors)

        techs = self._candidate_techniques()
        arm_ids = [t.tid for t in techs]

        # Wei failure-mode awareness (devdocs/14 §1): when the last round was
        # blocked while using techniques of one failure mode, prefer the OTHER
        # mode this round — same-mode repetition is the definition of insanity.
        # (Before this, technique_failure_mode() was dead code.)
        from jb_ape.jailbreak import FailureMode, technique_failure_mode

        if self.last_blocked_mode is FailureMode.COMPETING:
            alt = [t for t in techs if technique_failure_mode(t.tid) is FailureMode.MISMATCHED]
            if alt:
                techs, arm_ids = alt, [t.tid for t in alt]
        elif self.last_blocked_mode is FailureMode.MISMATCHED:
            alt = [t for t in techs if technique_failure_mode(t.tid) is FailureMode.COMPETING]
            if alt:
                techs, arm_ids = alt, [t.tid for t in alt]

        eps = self._eps(round_idx, max_rounds)
        chosen_id = self.bandit.select(self.objective.track, arm_ids, explore_eps=eps)
        chosen = next((t for t in techs if t.tid == chosen_id), techs[0])

        seeds: list[Variant] = []
        # On round 0, prefer curated track seeds + validated chains first —
        # they encode hard-won signal (armory/findings, armory/seeds).
        if round_idx == 0 and self.armory is not None:
            seeds.extend(self._seeds_from_armory(bundle_size))
            seeds.extend(self._seeds_from_chains(bundle_size))
        # Fill remaining slots with technique renders.
        for depth in range(max(0, bundle_size - len(seeds))):
            body = render(chosen, self.objective.goal)
            seeds.append(Variant(
                payload=body, technique=chosen.tid, scenario="",
                bypasses=[], mutation_chain=[chosen.tid], depth=depth,
            ))

        # Recon-aware seeding (devdocs/02 §7): on round 0, if recon detected
        # active defense layers, pre-apply the matching bypasses to the seeds
        # so the FIRST submission already counters the known defenses (instead
        # of attacking blind and wasting a round to discover them reactively).
        if round_idx == 0 and self.profile is not None and self.profile.detected_layers:
            seeds = [self._apply_recon_bypasses(s) for s in seeds]

        out = seeds[: max(bundle_size, len(seeds))]
        if self.hints:
            out = [_stamp_hint(s, self.hints[-1]) for s in out]
        return out

    def _apply_recon_bypasses(self, variant: Variant) -> Variant:
        """Fold recon-detected layers into a seed variant — and ACTUALLY
        transform the payload text (grok P0-2: the earlier version only
        stamped bypass metadata, so round-0 seeds still hit L1 raw).

        Applies the top-priority mechanical bypass per detected layer (max 2
        layers, to bound semantic drift), so the FIRST submission already
        counters the defenses recon discovered. Targets come from the recon
        wordlist when available, else the built-in defaults."""
        from jb_ape.defense import variant_bundle
        from jb_ape.rewriter import _LAYER_TO_BYPASSES

        if self.profile is None:
            return variant
        layers = list(self.profile.detected_layers)
        if not layers:
            return variant
        targets = set(getattr(self.profile, "l1_wordlist", None) or set()) or None
        body = variant.payload
        applied: list[str] = []
        for layer in layers[:2]:  # cap: 2 layers max
            for bid in _LAYER_TO_BYPASSES.get(layer, []):
                # Fixpoint loop: variant_bundle replaces ONE target word per
                # call (it returns a per-word variant list); iterate until no
                # word remains, so ALL recon-discovered L1 words are sanitized
                # (contract C1: not just the first).
                changed = False
                for _ in range(4):  # bound: at most 4 words per pass
                    try:
                        bodies = variant_bundle(body, bid, targets=targets, k=1)
                    except (TypeError, ValueError):
                        bodies = []
                    if not bodies:
                        break
                    body = bodies[0]
                    changed = True
                if changed:
                    applied.append(str(bid))
                    break
        bypasses = list(dict.fromkeys(variant.bypasses + applied))
        if not applied:
            return variant  # nothing transformable — don't pretend we did
        chain = variant.mutation_chain + ["RECON:" + ",".join(
            layer.value for layer in layers
        )] + applied
        return Variant(
            payload=body, technique=variant.technique,
            scenario=variant.scenario, bypasses=bypasses,
            mutation_chain=chain, depth=variant.depth,
        )

    def _seeds_from_armory(self, bundle_size: int) -> list[Variant]:
        out: list[Variant] = []
        if self.armory is None:
            return out
        for seed in self.armory.load_seeds(self.objective.track)[:bundle_size]:
            out.append(seed.to_variant(self.objective.goal))
        return out

    def _seeds_from_chains(self, bundle_size: int) -> list[Variant]:
        """Materialize the top effective chain for this track into a round-0
        seed (the chain's first element). Deeper chain elements are applied
        by the rewriter in subsequent rounds.

        Chains are usually technique-headed (e.g. ``["T-D3", "T-A1"]``) and
        only sometimes seed-headed (``["EMI-01", ...]``): when the head is a
        known technique, render it as the seed — otherwise the chain signal
        never reaches round 0 on technique-headed chains at all."""
        if self.armory is None:
            return []
        chains = self.armory.load_chains(self.objective.track)
        if not chains:
            return []
        top = max(chains, key=lambda c: c.asr_prior)
        first = top.sequence[0] if top.sequence else ""
        for seed in self.armory.load_seeds(self.objective.track):
            if seed.sid == first:
                return [seed.to_variant(self.objective.goal, depth=0)][:bundle_size]
        tech = TECHNIQUES.get(first)
        if tech is not None:
            return [Variant(
                payload=render(tech, self.objective.goal), technique=tech.tid,
                scenario="", bypasses=[], mutation_chain=[first], depth=0,
            )][:bundle_size]
        return []


def _stamp_hint(variant: Variant, hint: str) -> Variant:
    """Attach the operator's steering hint as a bracketed context line —
    byte-identical format to the tree planner's emission (dtree.Leaf.emit),
    so downstream consumers treat both planners the same."""
    return Variant(
        payload=variant.payload + "\n[operator context] " + hint,
        technique=variant.technique, scenario=variant.scenario,
        bypasses=list(variant.bypasses),
        mutation_chain=variant.mutation_chain + ["STEER"],
        depth=variant.depth,
    )


@dataclass
class TreeNode:
    """A search branch (TAP-style, devdocs/05 §6.1).

    Carries the judge's precise diagnosis so the next round's rewriter targets
    the *actual* blocked layer, not a score-based guess."""

    variant: Variant
    score: int = 0
    achieved: bool = False
    pruned: bool = False
    children: list[TreeNode] = field(default_factory=list)
    resistance_hit: set = field(default_factory=set)  # set[DefenseLayer]
    improve_hint: str = ""
    refusal_type: str = "none"


def prune(nodes: list[TreeNode], beam_width: int = 3, floor: int = 25) -> list[TreeNode]:
    """TAP-style pruning: drop branches below ``floor`` and keep top
    ``beam_width`` by score. Achieved branches are always retained."""
    alive = [n for n in nodes if (n.score >= floor or n.achieved)]
    for n in alive:
        n.pruned = False
    dead = [n for n in nodes if n not in alive]
    for n in dead:
        n.pruned = True
    alive.sort(key=lambda n: (n.achieved, n.score), reverse=True)
    return alive[:beam_width]


def dedupe_by_payload(nodes: list[TreeNode]) -> list[TreeNode]:
    """TAP de-duplication (devdocs/05 §6.1): skip payloads we've already tried."""
    seen: set[str] = set()
    out: list[TreeNode] = []
    for n in nodes:
        key = n.variant.payload.strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(n)
    return out


def on_topic_check(payload: str, goal: str, llm) -> bool:
    """TAP Phase-1 on-topic gate (devdocs/12 §2.2). Returns True if the payload
    still asks for the same information as the goal.

    Without an LLM, the gate is permissive (returns True) — the actual on-topic
    signal then comes from the judge after the (more expensive) target query.
    With an LLM, it runs a cheap YES/NO check that prunes drifted prompts BEFORE
    spending a target query on them.
    """
    if llm is None:
        return True
    import re

    from jb_ape.prompts import ON_TOPIC_SYSTEM, ON_TOPIC_USER_TEMPLATE

    try:
        raw = llm.chat(ON_TOPIC_SYSTEM, ON_TOPIC_USER_TEMPLATE.format(goal=goal, payload=payload))
    except Exception:  # noqa: BLE001 — pruning is advisory
        return True
    m = re.search(r"\[\[(YES|NO)\]\]", raw, re.IGNORECASE)
    if not m:
        return True  # unparseable → don't prune on a fluke
    return m.group(1).upper() == "YES"
