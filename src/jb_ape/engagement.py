"""Engagement — the stateful unit of invocation (devdocs/17).

Answers the integration question: how do OTHER tools/agents call jb_ape?
An outer orchestrating agent starts a long-running, budget-consuming red-team
ENGAGEMENT, steps it, polls compact VERDICTS (the built-in judge decides —
the caller consumes, never re-judges), steers it mid-flight, and can resume
after a process restart (snapshot persisted under armory/engagements/).

Transports on top of this module (same semantics):
  * MCP  — mcp_server.py: start/step/status/report/steer/stop tools
            (async-job pattern; state lives here + on disk)
  * CLI  — `jb-ape engage start|step|status|report`
  * Skill — skills/jb-ape/SKILL.md documents both for host agents
  * A2A  — future: the A2A task model maps 1:1 onto Engagement
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from jb_ape.catalog import SCENARIOS, build_objective, hijack_markers_for, mint_canary
from jb_ape.generator import Generator, RunConfig, RunCtx
from jb_ape.models import Objective, SubmissionResult, Track, Variant
from jb_ape.report import render_report

DEFAULT_STORE = Path("armory/engagements")


def _new_id() -> str:
    import secrets

    return "eng-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


@dataclass
class EngagementSpec:
    """Immutable creation parameters (serializable)."""

    url: str
    scenario: str | None = None
    track: str = "office"
    goal: str | None = None
    patterns: list[str] = field(default_factory=list)
    hijack: bool = False
    canary: str | None = None
    adapter: str = "dryrun"          # dryrun | browser | llm
    llm_model: str | None = None
    llm_base_url: str | None = None
    armory_root: str | None = "armory"
    planner_kind: str = "tree"
    budget: int = 20
    recon_budget: int = 6
    # 先侦察后攻击 (devdocs/02 §7) — same default as `jb-ape run`/RunConfig,
    # so all entry points behave alike; False = skip recon and attack blind.
    run_recon: bool = True
    bundle: int = 3
    max_rounds: int = 20

    def objective_and_markers(self) -> tuple[Objective, list[str]]:
        if self.scenario:
            sc = SCENARIOS[self.scenario]
            canary = self.canary or (mint_canary() if sc.canary else None)
            self.canary = canary  # write back: status()/snapshot must carry it
            obj = build_objective(sc, canary=canary)
            return obj, hijack_markers_for(sc, canary)
        canary = self.canary or (mint_canary() if self.hijack else None)
        self.canary = canary
        goal = self.goal or ""
        if canary:
            goal = f"{goal} [canary {canary}]"
        patterns = list(self.patterns) + ([canary] if canary else [])
        return (Objective(track=Track(self.track), goal=goal,
                          success_patterns=patterns),
                [canary] if (self.hijack and canary) else [])


class Engagement:
    """Stateful handle over one red-team engagement (devdocs/17 §2)."""

    def __init__(self, spec: EngagementSpec, browser, generator: Generator,
                 objective: Objective, markers: list[str]) -> None:
        self.id = _new_id()
        self.spec = spec
        self.browser = browser
        self.generator = generator
        self.objective = objective
        self.markers = markers
        self.ctx: RunCtx = RunCtx()
        self.steer_hints: list[str] = []
        self.created = time.time()
        self._prepared = False

    # -- lifecycle -------------------------------------------------------------
    def _ensure_prepared(self) -> None:
        if not self._prepared:
            self.ctx = self.generator.prepare(
                self.spec.url, self.spec.budget, self.spec.recon_budget)
            self._prepared = True

    def step(self, rounds: int = 1) -> dict:
        """Advance up to ``rounds`` generator rounds. Returns the status dict."""
        self._ensure_prepared()
        for _ in range(max(1, rounds)):
            if self.ctx.finished:
                break
            if self.ctx.rounds_done >= self.spec.max_rounds:
                break
            if self.ctx.submissions >= self.spec.budget:
                break
            self.generator.step_round(self.ctx, self.spec.url, self.spec.budget)
        self.save()
        return self.status()

    def steer(self, hint: str, disable: list[str] | None = None) -> dict:
        """Inject outer-agent guidance (devdocs/17 §4).

        ``hint`` rides as a bracketed ``[operator context]`` line on every
        subsequently emitted payload — observable and testable on BOTH
        planners (tree: TargetState.hints; bandit: Planner.hints).
        ``disable`` structurally removes technique ids (e.g. ``T-F1``) from
        routing. It is sticky: re-enable by restarting the engagement (a
        future enable API may lift it)."""
        self.steer_hints.append(hint)
        planner = self.generator.planner
        state = getattr(planner, "state", None)
        if state is not None:  # tree planner
            state.hints = list(self.steer_hints)
            if disable:
                state.disabled_families = set(state.disabled_families) | set(disable)
        if hasattr(planner, "hints"):  # flat planner consumes the same signals
            planner.hints = list(self.steer_hints)
        if disable and hasattr(planner, "disabled_families"):
            planner.disabled_families = (
                set(getattr(planner, "disabled_families", set())) | set(disable))
        self.save()
        return self.status()

    # -- verdicts ----------------------------------------------------------------
    def status(self) -> dict:
        """Compact VERDICT for the outer agent (they consume, not re-judge).
        Evidence excerpt included for arbitration."""
        best = self.ctx.best
        return {
            "id": self.id,
            "scenario": self.spec.scenario,
            "track": self.objective.track.value,
            "finished": self.ctx.finished,
            "achieved": bool(self.ctx.report and self.ctx.report.achieved),
            "confirmed": self.ctx.confirmed,
            "level": best.level if best else None,
            "score": best.score if best else 0,
            "submissions": self.ctx.submissions,
            "budget": self.spec.budget,
            "rounds": self.ctx.rounds_done,
            "canary": self.spec.canary,
            "evidence": (best.variant.payload[:200] if best else ""),
            "steer_hints": list(self.steer_hints),
        }

    def report_md(self) -> str:
        rep = self.ctx.report or self.generator._final_report(self.ctx)
        return render_report(rep, url=self.spec.url)

    # -- persistence ---------------------------------------------------------------
    def snapshot(self) -> dict:
        walker = getattr(self.generator.planner, "__dict__", {})
        snap = {
            "id": self.id, "created": self.created,
            "spec": self.spec.__dict__,
            "objective": {
                "track": self.objective.track.value, "goal": self.objective.goal,
                "patterns": self.objective.success_patterns,
                "fpr": self.objective.submit_max_false_positive_risk,
            },
            "markers": self.markers,
            "steer_hints": self.steer_hints,
            # Flat-planner steering (the tree planner persists the same two
            # signals via walker.state): must survive restarts on both planners.
            "planner": {
                "hints": list(getattr(self.generator.planner, "hints", []) or []),
                "disabled_families": sorted(
                    getattr(self.generator.planner, "disabled_families", set())
                    or set()),
            },
            # Target-side multi-turn history (LLMTargetClient) — restores
            # Crescendo/CFD continuity across process restarts (devdocs/17 §7).
            "target": {
                "histories": ({k: list(v) for k, v in self.browser._histories.items()}
                              if hasattr(self.browser, "_histories") else None),
                "current": getattr(self.browser, "_current", None),
            },
            "prepared": self._prepared,
            "ctx": {
                "confirmed": self.ctx.confirmed,
                "submissions": self.ctx.submissions,
                "rounds_done": self.ctx.rounds_done,
                "finished": self.ctx.finished,
                "achieved": bool(self.ctx.report and self.ctx.report.achieved),
                "best": ({
                    "payload": self.ctx.best.variant.payload,
                    "level": self.ctx.best.level, "score": self.ctx.best.score,
                    "arm_id": self.ctx.best.arm_id,
                    "chain": self.ctx.best.variant.mutation_chain,
                    "technique": self.ctx.best.variant.technique,
                } if self.ctx.best else None),
            },
            "walker": {
                k: v for k, v in walker.items()
                if k in ("_emitted_hashes", "_depth", "solved_paths",
                         "_xover_cursor", "state", "stats")
            },
            "bandit": {
                f"{getattr(tr, 'value', tr)}|{arm}": [a.alpha, a.beta]
                for (tr, arm), a in self.generator.bandit._arms.items()  # noqa: SLF001
            },
        }
        # state dataclass → plain dict (FailureMode enum → value)
        st = snap["walker"].get("state")
        if st is not None and hasattr(st, "__dict__"):
            sd = dict(st.__dict__)
            if isinstance(sd.get("layers"), set):
                sd["layers"] = [getattr(x, "value", x) for x in sd["layers"]]
            if isinstance(sd.get("disabled_families"), set):
                sd["disabled_families"] = sorted(sd["disabled_families"])
            if "last_blocked_mode" in sd and sd["last_blocked_mode"] is not None:
                sd["last_blocked_mode"] = getattr(
                    sd["last_blocked_mode"], "value", sd["last_blocked_mode"])
            snap["walker"]["state"] = sd
        if isinstance(snap["walker"].get("_emitted_hashes"), set):
            snap["walker"]["_emitted_hashes"] = sorted(snap["walker"]["_emitted_hashes"])
        # TreeWalker._LeafStat dataclasses → plain dicts (JSON-safe), so
        # prune/solve/fail state survives restarts with the rest of the walker.
        stats = snap["walker"].get("stats")
        if isinstance(stats, dict):
            snap["walker"]["stats"] = {
                lid: (vars(st) if hasattr(st, "__dict__") else st)
                for lid, st in stats.items()
            }
        return snap

    def save(self, store: Path | str | None = None) -> Path:
        store = Path(store) if store else DEFAULT_STORE
        store.mkdir(parents=True, exist_ok=True)
        fp = store / f"{self.id}.json"
        fp.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=1),
                      encoding="utf-8")
        return fp

    @classmethod
    def from_snapshot(cls, snap: dict, browser=None) -> Engagement:
        """Rebuild after a process restart (devdocs/17: state must survive).
        ``browser`` may be injected (tests / adapter reuse); else rebuilt
        from the spec (LLM target rebuilds its transport from spec)."""
        from jb_ape.cli import _adapter  # reuse adapter construction

        spec = EngagementSpec(**snap["spec"])
        browser = browser or _adapter(spec.adapter, spec.llm_model,
                                      spec.llm_base_url)
        obj_data = snap["objective"]
        objective = Objective(
            track=Track(obj_data["track"]), goal=obj_data["goal"],
            success_patterns=obj_data["patterns"],
            submit_max_false_positive_risk=obj_data.get("fpr", 0.10),
        )
        from jb_ape.facade import build_engine

        gen = build_engine(
            objective, browser=browser, armory_root=spec.armory_root,
            hijack_success_markers=snap["markers"] or None,
            planner_kind=spec.planner_kind,
            config=RunConfig(run_recon=False, bundle_size=spec.bundle,
                             max_rounds=spec.max_rounds),
        )
        eng = cls(spec, browser, gen, objective, snap["markers"])
        # restore target-side conversation history
        tgt = snap.get("target") or {}
        if tgt.get("histories") and hasattr(browser, "_histories"):
            browser._histories = {k: [dict(m) for m in v]
                                  for k, v in tgt["histories"].items()}
            browser._current = tgt.get("current")
        eng.id = snap["id"]
        eng.created = snap["created"]
        eng.steer_hints = list(snap["steer_hints"])
        ctx = snap["ctx"]
        eng.ctx.confirmed = ctx["confirmed"]
        eng.ctx.submissions = ctx["submissions"]
        eng.ctx.rounds_done = ctx["rounds_done"]
        eng._prepared = snap["prepared"]
        if ctx["best"]:
            b = ctx["best"]
            var = Variant(payload=b["payload"], technique=b["technique"],
                          mutation_chain=b["chain"])
            from jb_ape.generator import RunRecord

            eng.ctx.best = RunRecord(
                variant=var, submission=SubmissionResult(), level=b["level"],
                achieved=b["level"] in {"S", "A"}, score=b["score"],
                arm_id=b["arm_id"])
        # restore walker + bandit
        walker = getattr(gen.planner, "__dict__", None)
        if walker is not None:
            for key in ("_emitted_hashes", "_depth", "solved_paths",
                        "_xover_cursor"):
                if key in snap["walker"]:
                    val = snap["walker"][key]
                    if key == "_emitted_hashes":
                        val = set(val)
                    walker[key] = val
            st = snap["walker"].get("state")
            if st is not None and hasattr(gen.planner, "state"):
                from jb_ape.dtree import TargetState
                from jb_ape.jailbreak import FailureMode
                from jb_ape.models import DefenseLayer

                sd = dict(st)
                sd["layers"] = {DefenseLayer(x) for x in sd.get("layers", [])}
                sd["disabled_families"] = set(sd.get("disabled_families", []) or [])
                if sd.get("last_blocked_mode"):
                    sd["last_blocked_mode"] = FailureMode(sd["last_blocked_mode"])
                gen.planner.state = TargetState(**sd)
            stats_snap = snap["walker"].get("stats")
            if stats_snap and hasattr(gen.planner, "stats"):
                from jb_ape.dtree import _LeafStat

                fields = _LeafStat.__dataclass_fields__
                gen.planner.stats = {
                    lid: _LeafStat(**{k: v for k, v in d.items() if k in fields})
                    for lid, d in stats_snap.items()
                }
        for key, (alpha, beta) in snap.get("bandit", {}).items():
            tr_s, arm = key.split("|", 1)
            arm_obj = gen.bandit.arm(Track(tr_s), arm)
            arm_obj.alpha, arm_obj.beta = alpha, beta
        # restore flat-planner steering (tree planner restores via walker.state)
        psnap = snap.get("planner") or {}
        if hasattr(gen.planner, "hints"):
            gen.planner.hints = list(psnap.get("hints") or [])
            gen.planner.disabled_families = set(psnap.get("disabled_families") or [])
        return eng


# ───────────────────────── registry (MCP/CLI share it) ─────────────────────────

REGISTRY: dict[str, Engagement] = {}


def register(eng: Engagement) -> Engagement:
    REGISTRY[eng.id] = eng
    return eng


def get_engagement(eid: str) -> Engagement:
    eng = REGISTRY.get(eid)
    if eng is not None:
        return eng
    # try disk (server restart resilience)
    for store in (DEFAULT_STORE,):
        fp = Path(store) / f"{eid}.json"
        if fp.is_file():
            eng = Engagement.from_snapshot(json.loads(fp.read_text("utf-8")))
            return register(eng)
    raise KeyError(f"unknown engagement: {eid}")


def create_engagement(spec: EngagementSpec) -> Engagement:
    from jb_ape.cli import _adapter

    browser = _adapter(spec.adapter, spec.llm_model, spec.llm_base_url)
    objective, markers = spec.objective_and_markers()
    from jb_ape.facade import build_engine

    gen = build_engine(
        objective, browser=browser, armory_root=spec.armory_root,
        hijack_success_markers=markers or None,
        planner_kind=spec.planner_kind,
        config=RunConfig(run_recon=spec.run_recon, bundle_size=spec.bundle,
                         max_rounds=spec.max_rounds),
    )
    return register(Engagement(spec, browser, gen, objective, markers))
