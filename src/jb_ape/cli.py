"""jb-ape CLI — one-command agent red-teaming.

Subcommands:
  scenarios                       list the preset problem catalog
  recon    --url X [--adapter ..] probe defenses, print the DefenseProfile
  run      --scenario S --url X   full loop on ONE scenario, print report
  sweep    [--track T] --url X    run every matching scenario on a small budget

Examples:
  jb-ape scenarios
  jb-ape run --scenario tool-call-hijack --url https://t/ --adapter browser
  jb-ape run --track office --goal "leak sysprompt" --pattern "(?i)you are" \
             --url https://t/ --adapter llm --llm-model gpt-4o-mini
  jb-ape sweep --track coding --url https://t/ --adapter llm --llm-model m

Exit codes: 0 normal; 1 with ``--strict`` when the objective was not achieved.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jb_ape.catalog import (
    SCENARIOS,
    Scenario,
    build_objective,
    hijack_markers_for,
    mint_canary,
    scenarios_for_track,
)
from jb_ape.models import Objective, Track
from jb_ape.report import render_report


def _adapter(name: str, llm_model: str | None, llm_base_url: str | None):
    if name == "dryrun":
        from jb_ape.browser import DryRunBrowserClient

        return DryRunBrowserClient()
    if name == "browser":
        from jb_ape.targets import AgentBrowserClient

        return AgentBrowserClient()
    if name == "llm":
        from jb_ape.targets import LLMTargetClient

        if not llm_model:
            raise SystemExit("--adapter llm requires --llm-model")
        return LLMTargetClient(model=llm_model, base_url=llm_base_url)
    raise SystemExit(f"unknown adapter: {name}")


def _llms(model: str | None, base_url: str | None):
    """Separate generator/judge instances (devdocs/05 §3.3 bias discipline)."""
    if not model:
        return None, None
    from jb_ape.llm import OpenAICompatibleLLM

    gen = OpenAICompatibleLLM(model=model, base_url=base_url, temperature=1.0)
    judge = OpenAICompatibleLLM(model=model, base_url=base_url, temperature=0.0)
    return gen, judge


def _objective_from(args) -> tuple[Objective, list[str]]:
    """Build (objective, hijack_markers) from --scenario or raw flags."""
    if args.scenario:
        sc: Scenario = SCENARIOS[args.scenario]
        canary = mint_canary() if sc.canary else None
        obj = build_objective(sc, canary=canary)
        markers = hijack_markers_for(sc, canary)
        return obj, markers
    track = Track(args.track)
    goal = args.goal
    if not goal:
        raise SystemExit("--goal is required without --scenario")
    canary = mint_canary() if args.canary else None
    if canary:
        goal = f"{goal} [canary {canary}]"
    patterns = list(args.pattern or [])
    if canary:
        patterns.append(canary)
    return (Objective(track=track, goal=goal, success_patterns=patterns),
            [canary] if (args.hijack and canary) else [])


def cmd_scenarios(_args) -> int:
    print(f"{'scenario':<22} {'problem':<20} {'track':<11} canary hijack")
    for sc in SCENARIOS.values():
        print(f"{sc.sid:<22} {sc.problem:<20} {sc.track.value:<11} "
              f"{'yes' if sc.canary else '-':<6} {'yes' if sc.hijack else '-'}")
    return 0


def cmd_recon(args) -> int:
    from jb_ape.armory import Armory
    from jb_ape.recon import Recon

    browser = _adapter(args.adapter, args.llm_model, args.llm_base_url)
    report = Recon(armory=Armory(args.armory)).run(browser, args.url,
                                                   budget=args.recon_budget)
    p = report.profile
    layers = ", ".join(sorted(layer.value for layer in p.resistance())) or "(none)"
    print(f"[recon] cost={report.cost} active-defenses={layers}")
    if p.l1out_redacts:
        print("[recon] ⚠️ L1' redacts raw output → output-side encoding required")
    if p.ppl_filter_active:
        print("[recon] ⚠️ PPL filter active → readable techniques preferred")
    if p.system_prompt_leak:
        print(f"[recon] 🎯 sysprompt leaked: {p.system_prompt_leak[:120]}")
    if p.agent_tools:
        print(f"[recon] tools: {', '.join(p.agent_tools[:10])}")
    return 0


def cmd_run(args) -> int:
    from jb_ape.facade import quick_run
    from jb_ape.generator import RunConfig

    obj, markers = _objective_from(args)
    browser = _adapter(args.adapter, args.llm_model, args.llm_base_url)
    gen_llm, judge_llm = _llms(args.llm_model, args.llm_base_url)
    print(f"[run] scenario={args.scenario or '-'} track={obj.track.value} "
          f"adapter={args.adapter}")
    print(f"[run] goal: {obj.goal[:100]}")
    rep = quick_run(
        obj, args.url, browser=browser,
        generator_llm=gen_llm, judge_llm=judge_llm,
        budget=args.budget,
        config=RunConfig(run_recon=not args.no_recon,
                         bundle_size=args.bundle, max_rounds=args.rounds),
        armory_root=args.armory,
        hijack_success_markers=markers or None,
        planner_kind=args.planner,
    )
    out = render_report(rep, url=args.url)
    print(out)
    if args.out:
        _write(args.out, f"report-{'-'.join((args.scenario or 'goal').split())}.md", out)
    if args.strict and not rep.achieved:
        return 1
    return 0


def cmd_sweep(args) -> int:
    from jb_ape.facade import quick_run
    from jb_ape.generator import RunConfig

    track = Track(args.track) if args.track else None
    browser = _adapter(args.adapter, args.llm_model, args.llm_base_url)
    gen_llm, judge_llm = _llms(args.llm_model, args.llm_base_url)
    rows = []
    for sc in scenarios_for_track(track):
        canary = mint_canary() if sc.canary else None
        obj = build_objective(sc, canary=canary)
        markers = hijack_markers_for(sc, canary)
        rep = quick_run(
            obj, args.url, browser=browser,
            generator_llm=gen_llm, judge_llm=judge_llm,
            budget=args.each_budget,
            config=RunConfig(run_recon=False, bundle_size=2, max_rounds=2),
            armory_root=args.armory,
            hijack_success_markers=markers or None,
            planner_kind=args.planner,
        )
        rows.append((sc, rep))
        mark = "✅" if rep.achieved else "❌"
        print(f"{mark} {sc.sid:<22} {sc.problem:<20} "
              f"subs={rep.submissions:<3} best={rep.best.score if rep.best else 0}")
        if args.out:
            _write(args.out, f"sweep-{sc.sid}.md",
                   render_report(rep, url=args.url))
    hit = sum(1 for _, r in rows if r.achieved)
    print(f"[sweep] {hit}/{len(rows)} scenarios achieved")
    return 0


def cmd_engage(args) -> int:
    import json

    from jb_ape.engagement import EngagementSpec, get_engagement

    if args.engage_cmd == "start":
        spec = EngagementSpec(
            url=args.url, scenario=args.scenario, track=args.track,
            goal=args.goal, adapter=args.adapter, llm_model=args.llm_model,
            llm_base_url=args.llm_base_url, budget=args.budget,
            max_rounds=args.rounds, planner_kind=args.planner,
            run_recon=not args.no_recon,
            armory_root="armory",
        )
        from jb_ape.engagement import create_engagement

        print(json.dumps(create_engagement(spec).status(), ensure_ascii=False, indent=1))
        return 0
    eng = get_engagement(args.id)
    if args.engage_cmd == "step":
        print(json.dumps(eng.step(rounds=args.rounds), ensure_ascii=False, indent=1))
    elif args.engage_cmd == "status":
        print(json.dumps(eng.status(), ensure_ascii=False, indent=1))
    elif args.engage_cmd == "steer":
        print(json.dumps(eng.steer(args.hint, disable=args.disable),
                         ensure_ascii=False, indent=1))
    elif args.engage_cmd == "report":
        print(eng.report_md())
    return 0


def _write(out_dir: str, name: str, text: str) -> None:
    base = Path(out_dir)
    base.mkdir(parents=True, exist_ok=True)
    (base / name).write_text(text, encoding="utf-8")
    print(f"[out] {base / name}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jb-ape",
                                 description="Agent AI red-team tool (authorized use only)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scenarios", help="list the preset problem catalog")

    pr = sub.add_parser("recon", help="probe a target's defenses")
    _common(pr, url=True)

    pu = sub.add_parser("run", help="run one scenario/objective end-to-end")
    _common(pu, url=True)
    pu.add_argument("--scenario", choices=sorted(SCENARIOS))
    pu.add_argument("--track", default="office")
    pu.add_argument("--goal")
    pu.add_argument("--pattern", action="append",
                    help="success regex (repeatable)")
    pu.add_argument("--canary", action="store_true",
                    help="mint+watch a canary token (raw-goal mode)")
    pu.add_argument("--hijack", action="store_true",
                    help="enable tool-call hijack judging (raw-goal mode)")
    pu.add_argument("--no-recon", action="store_true")
    pu.add_argument("--strict", action="store_true",
                    help="exit 1 if objective not achieved")
    pu.add_argument("--planner", default="bandit", choices=["bandit", "tree"])
    pu.add_argument("--out", help="write the markdown report to this directory")

    pe = sub.add_parser("engage", help="stateful engagement (MCP-equivalent)")
    pes = pe.add_subparsers(dest="engage_cmd", required=True)
    st = pes.add_parser("start")
    st.add_argument("--url", required=True)
    st.add_argument("--scenario")
    st.add_argument("--track", default="office")
    st.add_argument("--goal")
    st.add_argument("--adapter", default="dryrun",
                    choices=["dryrun", "browser", "llm"])
    st.add_argument("--llm-model")
    st.add_argument("--llm-base-url")
    st.add_argument("--budget", type=int, default=20)
    st.add_argument("--rounds", type=int, default=20)
    st.add_argument("--planner", default="tree", choices=["bandit", "tree"])
    st.add_argument("--no-recon", action="store_true",
                    help="skip the recon phase (attack blind)")
    stp = pes.add_parser("step")
    stp.add_argument("--id", required=True)
    stp.add_argument("--rounds", type=int, default=1)
    sts = pes.add_parser("status")
    sts.add_argument("--id", required=True)
    stg = pes.add_parser("steer")
    stg.add_argument("--id", required=True)
    stg.add_argument("--hint", required=True)
    stg.add_argument("--disable", action="append",
                    help="technique id removed from routing (repeatable)")
    strp = pes.add_parser("report")
    strp.add_argument("--id", required=True)

    ps = sub.add_parser("sweep", help="run every scenario (optionally per track)")
    _common(ps, url=True)
    ps.add_argument("--track")
    ps.add_argument("--each-budget", type=int, default=5)
    ps.add_argument("--planner", default="bandit",
                    choices=["bandit", "tree"])
    ps.add_argument("--out")
    return p


def _common(sp, url: bool = False) -> None:
    if url:
        sp.add_argument("--url", required=True)
    sp.add_argument("--adapter", default="dryrun",
                    choices=["dryrun", "browser", "llm"])
    sp.add_argument("--armory", default="armory")
    sp.add_argument("--recon-budget", type=int, default=6)
    sp.add_argument("--budget", type=int, default=20)
    sp.add_argument("--bundle", type=int, default=3)
    sp.add_argument("--rounds", type=int, default=8)
    sp.add_argument("--llm-model")
    sp.add_argument("--llm-base-url")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "scenarios":
        return cmd_scenarios(args)
    if args.cmd == "recon":
        return cmd_recon(args)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "sweep":
        return cmd_sweep(args)
    if args.cmd == "engage":
        return cmd_engage(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
