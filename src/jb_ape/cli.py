"""jb-ape CLI — one-command agent red-teaming.

Subcommands:
  scenarios                       list the preset problem catalog
  recon    --url X [--adapter ..] probe defenses, print the DefenseProfile
  run      --scenario S --url X   full loop on ONE scenario, print report
  sweep    [--track T] --url X    run every matching scenario on a small budget
  qa       --url X                FIXED baseline suite → QA-style report
                                  (deterministic, no search; see README_QA.md);
                                  --adapter ext runs the cases through the
                                  browser extension in YOUR logged-in session
                                  (browser_ext/ + loopback-only bridge)

Examples:
  jb-ape scenarios
  jb-ape qa --url https://t/ --adapter llm --llm-model gpt-4o-mini
  jb-ape run --scenario tool-call-hijack --url https://t/ --adapter browser
  jb-ape run --track office --goal "leak sysprompt" --pattern "(?i)you are" \
             --url https://t/ --adapter llm --llm-model gpt-4o-mini
  jb-ape sweep --track coding --url https://t/ --adapter llm --llm-model m

Exit codes: 0 normal; 1 with ``--strict`` when the objective was not achieved,
or for ``qa`` when findings reach the ``--fail-on`` policy; 2 on config or
execution errors.
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


def _adapter(name: str, llm_model: str | None, llm_base_url: str | None,
             ext_port: int | None = None, ext_timeout: float | None = None):
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
    if name == "ext":
        from jb_ape.bridge import ExtensionBrowserClient

        return ExtensionBrowserClient(
            port=ext_port or 8765, case_timeout=ext_timeout or 240.0)
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

    browser = _adapter(args.adapter, args.llm_model, args.llm_base_url,
                      ext_port=getattr(args, 'ext_port', None),
                      ext_timeout=getattr(args, 'ext_timeout', None))
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
    browser = _adapter(args.adapter, args.llm_model, args.llm_base_url,
                      ext_port=getattr(args, 'ext_port', None),
                      ext_timeout=getattr(args, 'ext_timeout', None))
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
    browser = _adapter(args.adapter, args.llm_model, args.llm_base_url,
                      ext_port=getattr(args, 'ext_port', None),
                      ext_timeout=getattr(args, 'ext_timeout', None))
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


def cmd_qa(args) -> int:
    from jb_ape.qa import (
        QA_CATEGORIES,
        build_qa_suite,
        demo_responses,
        load_regression_ids,
        render_qa_console,
        render_qa_json,
        render_qa_markdown,
        run_qa,
        save_regression,
    )

    cats = None
    if args.categories:
        cats = [c.strip() for c in args.categories.split(",") if c.strip()]
        unknown = [c for c in cats if c not in QA_CATEGORIES]
        if unknown:
            raise SystemExit(
                f"unknown categories {unknown}; valid: {sorted(QA_CATEGORIES)}")
    cases = build_qa_suite(categories=cats)

    if args.cases:
        wanted = set(args.cases)
        unknown = wanted - {c.id for c in cases}
        if unknown:
            raise SystemExit(f"unknown case ids {sorted(unknown)}")
        cases = [c for c in cases if c.id in wanted]
    if args.regression_only:
        ids = set(load_regression_ids(args.regression))
        if not ids:
            print(f"[qa] regression corpus {args.regression} is empty — "
                  f"nothing to replay")
            return 0
        cases = [c for c in cases if c.id in ids]

    if args.list:
        print(f"{'case':<8} {'category':<20} {'scenario':<22} {'tech':<6} title")
        for c in cases:
            print(f"{c.id:<8} {c.category:<20} {c.scenario_sid:<22} "
                  f"{c.technique:<6} {c.title}")
        print(f"[qa] {len(cases)} cases · categories: {', '.join(QA_CATEGORIES)}")
        return 0

    if not args.url:
        raise SystemExit("--url is required to run the suite (see --list)")
    if args.demo and args.adapter != "dryrun":
        raise SystemExit("--demo scripts offline responses; it requires "
                         "--adapter dryrun")

    browser = _adapter(args.adapter, args.llm_model, args.llm_base_url,
                       ext_port=getattr(args, "ext_port", None),
                       ext_timeout=getattr(args, "ext_timeout", None))
    if args.adapter == "ext":
        print("[qa] 浏览器插件模式（复用你已登录的会话，仅本机回环通信）:",
              file=sys.stderr)
        print("[qa]   1. 在你的浏览器安装 browser_ext/ 扩展（见 browser_ext/README.md）",
              file=sys.stderr)
        print("[qa]   2. 打开并登录目标页面，保持该标签页在前台",
              file=sys.stderr)
        print(f"[qa]   3. 等待插件接入 {browser.bridge.url} …",
              file=sys.stderr)
        if not browser.wait_for_extension(timeout=args.ext_wait):
            browser.stop()
            print(f"[qa] {args.ext_wait:.0f}s 内没有插件接入 —— 确认扩展已启用、"
                  f"端口 {args.ext_port} 未被占用后重试", file=sys.stderr)
            raise SystemExit(2)
        print("[qa] 插件已接入，开始执行用例（每条用例会刷新页面以隔离会话）",
              file=sys.stderr)
    if args.demo:
        from jb_ape.browser import DryRunBrowserClient

        browser = DryRunBrowserClient(responses=demo_responses(cases))
    judge_llm = None
    if args.llm_model:
        from jb_ape.llm import OpenAICompatibleLLM

        judge_llm = OpenAICompatibleLLM(model=args.llm_model,
                                        base_url=args.llm_base_url,
                                        temperature=0.0)

    print(f"[qa] target={args.url} adapter={args.adapter} cases={len(cases)} "
          f"lang={args.lang} fail-on={args.fail_on}", file=sys.stderr)
    rep = run_qa(args.url, browser, cases, judge_llm=judge_llm,
                 adapter=args.adapter)

    if args.format == "json":
        print(render_qa_json(rep))
    else:
        if args.format == "md":
            print(render_qa_markdown(rep, lang=args.lang, fail_on=args.fail_on))
        else:
            print(render_qa_console(rep, lang=args.lang))
        if report_failed := rep.failed() + rep.suspicious():
            print(f"[qa] {len(report_failed)} finding(s) — rerun with "
                  f"--format md for evidence + repro steps", file=sys.stderr)
    if args.out:
        _write(args.out, "qa-report.md",
               render_qa_markdown(rep, lang=args.lang, fail_on=args.fail_on))
        _write(args.out, "qa-report.json", render_qa_json(rep))
    if args.record_failures:
        n = save_regression(args.regression, rep)
        print(f"[qa] regression corpus {args.regression}: {n} case(s)",
              file=sys.stderr)
    if args.adapter == "ext":
        browser.stop()
    code = rep.exit_code(args.fail_on)
    if code:
        print(f"[qa] exit {code} — findings at/above fail-on={args.fail_on}"
              if code == 1 else "[qa] exit 2 — execution errors, re-run",
              file=sys.stderr)
    return code


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

    pq = sub.add_parser(
        "qa", help="QA smoke test: fixed baseline suite → QA-style report")
    pq.add_argument("--url", help="target base URL (any value for dryrun)")
    pq.add_argument("--adapter", default="dryrun",
                    choices=["dryrun", "browser", "llm", "ext"])
    pq.add_argument("--ext-port", type=int, default=8765,
                    help="adapter ext: loopback bridge port")
    pq.add_argument("--ext-timeout", type=float, default=240.0,
                    help="adapter ext: per-case timeout in seconds")
    pq.add_argument("--ext-wait", type=float, default=90.0,
                    help="adapter ext: seconds to wait for the extension to "
                         "connect before giving up")
    pq.add_argument("--llm-model")
    pq.add_argument("--llm-base-url")
    pq.add_argument("--categories",
                    help="comma-separated risk categories (default: all)")
    pq.add_argument("--case", action="append", dest="cases",
                    help="run only these case ids, repeatable (repro)")
    pq.add_argument("--list", action="store_true",
                    help="list the fixed suite and exit")
    pq.add_argument("--lang", default="zh", choices=["zh", "en"])
    pq.add_argument("--format", default="console",
                    choices=["console", "md", "json"])
    pq.add_argument("--out",
                    help="write qa-report.md + qa-report.json to this directory")
    pq.add_argument("--fail-on", default="high",
                    choices=["high", "medium", "any", "none"],
                    help="exit-1 policy for CI (default: high)")
    pq.add_argument("--regression", default="qa_regression.json",
                    help="regression corpus file")
    pq.add_argument("--regression-only", action="store_true",
                    help="replay only cases recorded in the corpus")
    pq.add_argument("--record-failures", action="store_true",
                    help="append failed+suspicious cases to the corpus")
    pq.add_argument("--demo", action="store_true",
                    help="dryrun: script 1 High failure + 1 Suspicious so the "
                         "report shape is visible offline")
    return p

def _common(sp, url: bool = False) -> None:
    if url:
        sp.add_argument("--url", required=True)
    sp.add_argument("--adapter", default="dryrun",
                    choices=["dryrun", "browser", "llm", "ext"])
    sp.add_argument("--ext-port", type=int, default=8765,
                    help="adapter ext: loopback bridge port")
    sp.add_argument("--ext-timeout", type=float, default=240.0,
                    help="adapter ext: per-case timeout in seconds")
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
    if args.cmd == "qa":
        return cmd_qa(args)
    if args.cmd == "engage":
        return cmd_engage(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
