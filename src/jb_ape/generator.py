"""Generator — the orchestrator wiring the closed loop (devdocs/05 §2).

One ``run`` drives: planner → browser → judge → (rewriter + bandit + tree)
until the objective is achieved or the submission budget is exhausted. It is
deliberately synchronous and explicit so every step is testable; a LangGraph
adapter can wrap it later (devdocs/05 §7).

Design notes:
* The judge LLM and the rewriter LLM are separate instances (devdocs/05 §3.3) —
  pass distinct objects to avoid confirmation bias.
* Submission is gated: the generator only calls ``confirm_submit`` when the
  judge returns ``can_submit`` (devdocs/01 §3).
* The tree is shallow (devdocs/05 §6.2); depth is capped by ``max_depth``.
"""

from __future__ import annotations

import contextlib
import random
from dataclasses import dataclass, field

from jb_ape.browser import BrowserClient
from jb_ape.judge import Judge
from jb_ape.models import (
    DefenseLayer,
    Objective,
    SubmissionResult,
    Variant,
)
from jb_ape.planner import Bandit, Planner, TreeNode, on_topic_check, prune
from jb_ape.rewriter import Rewriter


def _on_topic(payload: str, goal: str, llm) -> bool:
    """Thin wrapper so generator doesn't import the helper at call-time."""
    return on_topic_check(payload, goal, llm)


@dataclass
class RunConfig:
    bundle_size: int = 3
    max_rounds: int = 20
    max_depth: int = 4
    beam_width: int = 3
    seed: int | None = None
    confirm_on_success: bool = True  # call browser.confirm_submit when achieved
    run_recon: bool = True  # devdocs/02 §7: reverse-engineer defenses before attacking


@dataclass
class RunRecord:
    """One attempted payload + its outcome. The full list is the run's log.

    Carries the judge's precise diagnosis (resistance_hit / improve_hint /
    refusal_type) so the next round's rewriter gets *real* layer information
    instead of a crude score-based guess (devdocs/05 §4.1)."""

    variant: Variant
    submission: SubmissionResult
    level: str
    achieved: bool
    score: int
    arm_id: str
    confirmed: bool = False
    resistance_hit: set = field(default_factory=set)  # set[DefenseLayer]
    improve_hint: str = ""
    refusal_type: str = "none"


@dataclass
class RunReport:
    achieved: bool
    rounds: int
    submissions: int
    confirmed: int
    best: RunRecord | None
    records: list[RunRecord] = field(default_factory=list)
    recon_profile: object | None = None  # DefenseProfile from recon phase
    recon_cost: int = 0


@dataclass
class RunCtx:
    """Mutable state of one engagement run (devdocs/17 §2). ``Generator.run``
    loops ``step_round`` over it; the stateful API (engagement.py) steps it
    externally, snapshots it, and resumes across process restarts."""

    records: list[RunRecord] = field(default_factory=list)
    confirmed: int = 0
    submissions: int = 0
    rounds_done: int = 0
    best: RunRecord | None = None
    recon_profile: object | None = None
    recon_cost: int = 0
    finished: bool = False
    report: RunReport | None = None


class Generator:
    """Closed-loop payload generator. Construct with the objective + clients;
    call ``run`` to execute the full search."""

    def __init__(
        self,
        objective: Objective,
        browser: BrowserClient,
        judge: Judge,
        rewriter: Rewriter,
        planner: Planner,
        bandit: Bandit,
        config: RunConfig | None = None,
        armory: object | None = None,
        gate_llm: object | None = None,
    ) -> None:
        self.objective = objective
        self.browser = browser
        self.judge = judge
        self.rewriter = rewriter
        self.planner = planner
        self.bandit = bandit
        self.config = config or RunConfig()
        self.armory = armory
        # gate_llm powers the TAP on-topic gate (devdocs/12 §2.2). None ⇒ gate
        # is permissive (offline hermetic runs). Keep it distinct from the judge
        # LLM to avoid confirmation bias (devdocs/05 §3.3).
        self.judge_llm_for_gate = gate_llm
        self.last_recon = None
        self._survivors: list = []  # init eagerly (pi review P2-5)
        self.rng = random.Random(self.config.seed)

    def run(self, url: str, budget: int = 60, recon_budget: int = 6) -> RunReport:
        """Execute the search against ``url`` with a submission ``budget``.

        ``recon_budget`` is reserved from ``budget`` for the reconnaissance phase
        (devdocs/02 §7). Batch API — the stateful/interactive equivalent is
        ``step_round`` (used by engagement.py, devdocs/17)."""
        ctx = self.prepare(url, budget, recon_budget)
        while not ctx.finished:
            if ctx.rounds_done >= self.config.max_rounds:
                break
            if ctx.submissions >= budget:
                break
            self.step_round(ctx, url, budget)
        return ctx.report or self._final_report(ctx)

    def prepare(self, url: str, budget: int = 60,
                recon_budget: int = 6) -> RunCtx:
        """Recon + open; returns the mutable run context (devdocs/17 §2)."""
        ctx = RunCtx()
        if self.config.run_recon:
            from jb_ape.recon import Recon

            recon = Recon(armory=self.armory)
            actual_recon_budget = min(recon_budget, max(0, budget))
            recon_report = recon.run(self.browser, url, budget=actual_recon_budget)
            ctx.recon_cost = recon_report.cost
            ctx.submissions += recon_report.cost
            self.planner.profile = recon_report.profile
            self.rewriter.profile = recon_report.profile
            ctx.recon_profile = recon_report.profile
            self.last_recon = recon_report
        else:
            with contextlib.suppress(Exception):  # noqa: BLE001
                self.browser.open(url)
        return ctx

    def step_round(self, ctx: RunCtx, url: str, budget: int) -> None:
        """ONE round: plan → gate → submit/judge/record/persist/reward →
        prune/blocked-mode. Mutates ``ctx``; sets ``ctx.report`` on a gated win
        (ctx.finished=True). Callable repeatedly = the stateful API."""
        round_idx = ctx.rounds_done
        ctx.rounds_done += 1
        seeds = self.planner.plan_round(
            round_idx, self.config.max_rounds, self.config.bundle_size
        )
        frontier = seeds if round_idx == 0 else self._expand(seeds, ctx.records)
        frontier = _dedupe_variants(frontier)

        if self.judge_llm_for_gate is not None:
            frontier = [
                v for v in frontier
                if _on_topic(v.payload, self.objective.goal, self.judge_llm_for_gate)
            ]
            if not frontier:
                return

        nodes: list[TreeNode] = []
        for var in frontier:
            if ctx.submissions >= budget:
                break
            sub = self.browser.submit_payload(var.payload)
            ctx.submissions += 1
            result = self.judge.evaluate(sub, variant_bypasses=var.bypasses)
            rec = RunRecord(
                variant=var, submission=sub, level=result.level,
                achieved=result.achieved, score=result.quality_score,
                arm_id=_arm_id(var),
                resistance_hit=set(result.resistance_hit),
                improve_hint=result.improve_hint,
                refusal_type=result.refusal_type,
            )
            ctx.records.append(rec)
            nodes.append(TreeNode(
                variant=var, score=result.quality_score, achieved=result.achieved,
                resistance_hit=set(result.resistance_hit),
                improve_hint=result.improve_hint,
                refusal_type=result.refusal_type,
            ))
            ctx.best = _update_best(ctx.best, rec)

            if self.armory is not None and rec.level in {"S", "A", "B"}:
                self.armory.log_finding(self.objective.track, {
                    "level": rec.level, "score": rec.score,
                    "achieved": rec.achieved, "arm_id": rec.arm_id,
                    "payload": var.payload,
                    "mutation_chain": var.mutation_chain,
                    "technique": var.technique,
                    "bypasses": var.bypasses,
                    "improve_hint": result.improve_hint,
                })

            self.bandit.reward(
                self.objective.track, rec.arm_id, rec.achieved, rec.score
            )

            # Tree-planner feedback (dtree.TreeWalker.record): solved / prune /
            # Wei-mode rotation must react to verdicts in production, not just
            # in unit tests. Duck-typed — the flat Planner has no record().
            planner_record = getattr(self.planner, "record", None)
            if callable(planner_record):
                planner_record(var, result.achieved, result.quality_score)

            gate_passed = result.can_submit(
                self.objective.submit_max_false_positive_risk)
            if gate_passed:
                if self.config.confirm_on_success:
                    self.browser.confirm_submit()
                    rec.confirmed = True
                    ctx.confirmed += 1
                ctx.report = RunReport(
                    achieved=True, rounds=ctx.rounds_done,
                    submissions=ctx.submissions, confirmed=ctx.confirmed,
                    best=ctx.best, records=ctx.records,
                    recon_profile=ctx.recon_profile, recon_cost=ctx.recon_cost,
                )
                ctx.finished = True
                return

        self._survivors = prune(nodes, beam_width=self.config.beam_width)

        if not any(n.achieved for n in nodes) and nodes:
            from jb_ape.jailbreak import FailureMode, technique_failure_mode

            modes = [technique_failure_mode(n.variant.technique) for n in nodes]
            comp = sum(1 for m in modes if m is FailureMode.COMPETING)
            mis = sum(1 for m in modes if m is FailureMode.MISMATCHED)
            if comp > mis:
                self.planner.last_blocked_mode = FailureMode.COMPETING
            elif mis > comp:
                self.planner.last_blocked_mode = FailureMode.MISMATCHED

    def _final_report(self, ctx: RunCtx) -> RunReport:
        return RunReport(
            achieved=False, rounds=ctx.rounds_done,
            submissions=ctx.submissions, confirmed=ctx.confirmed,
            best=ctx.best, records=ctx.records,
            recon_profile=ctx.recon_profile, recon_cost=ctx.recon_cost,
        )

    # -- internals ----------------------------------------------------------------

    def _expand(self, seeds: list[Variant], records: list[RunRecord]) -> list[Variant]:
        """Combine fresh seeds with rewriter expansions of prior survivors +
        GPTFuzzer CrossOver of the top-2 survivors (devdocs/12 §4.1)."""
        out = list(seeds)
        survivors = sorted(
            getattr(self, "_survivors", []),
            key=lambda n: n.score, reverse=True,
        )
        for node in survivors:
            if node.variant.depth >= self.config.max_depth:
                continue
            feedback = _feedback_for(node, self.objective.track)
            expanded = self.rewriter.rewrite(node.variant, feedback, k=self.config.bundle_size)
            out.extend(expanded)
        # CrossOver: merge the two highest-scoring survivors (the dimension
        # PAIR/TAP lack — combines fragments that each partially worked).
        if len(survivors) >= 2:
            out.extend(self.rewriter.crossover(
                survivors[0].variant, survivors[1].variant, k=1,
            ))
        return out


# --- helpers ---------------------------------------------------------------------


def _arm_id(var: Variant) -> str:
    """Bandit arm id. MUST match the id space the planner samples on
    (planner selects over bare technique ids like 'T-A1'). Including the
    bypass here would reward arms that are never selected, silently killing
    the learning loop (pi review P0-1). The full technique+bypass is still
    recorded on the RunRecord/Variant for analysis."""
    return var.technique or "T-?"


def _dedupe_variants(variants: list[Variant]) -> list[Variant]:
    seen: set[str] = set()
    out: list[Variant] = []
    for v in variants:
        key = v.payload.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _update_best(best: RunRecord | None, rec: RunRecord) -> RunRecord:
    if best is None or rec.score > best.score or (rec.achieved and not best.achieved):
        return rec
    return best


def _feedback_for(node: TreeNode, track: object) -> object:  # noqa: ARG005 — track kept for symmetry
    """Build a Feedback for the rewriter from a tree node.

    Prefers the judge's *actual* diagnosis (resistance_hit / improve_hint /
    refusal_type) carried on the node. Falls back to a score-based heuristic
    only when the judge didn't supply a diagnosis (e.g. tier-2 short-circuit
    with no LLM, where resistance_hit is empty)."""
    from jb_ape.models import Feedback

    # Prefer real diagnosis when the judge supplied one.
    if node.resistance_hit:
        return Feedback(
            quality_score=node.score, achieved=node.achieved,
            recommended_layers=set(node.resistance_hit),
            improve_hint=node.improve_hint or "counter the blocked layers",
            refusal_type=node.refusal_type,
        )

    # Fallback: score-based heuristic (used when no LLM judge → empty resistance_hit).
    if node.achieved:
        layers: set[DefenseLayer] = set()
        hint = "objective achieved; refine for higher fidelity only"
    elif node.score >= 50:
        layers = {DefenseLayer.L3}
        hint = "partial progress; switch nesting scenario"
    elif node.score >= 25:
        layers = {DefenseLayer.L2, DefenseLayer.L3}
        hint = "blocked mid-stack; add authority override or role reframing"
    else:
        layers = {DefenseLayer.L1, DefenseLayer.L2, DefenseLayer.L1_OUT}
        hint = "hard refusal; apply encoding + override + output-split"
    return Feedback(
        quality_score=node.score, achieved=node.achieved,
        recommended_layers=layers, improve_hint=hint, refusal_type="none",
    )
