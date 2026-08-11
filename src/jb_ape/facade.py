"""High-level facade — the single entry point other agents should use.

Example::

    from jb_ape import quick_run, Objective, Track
    report = quick_run(
        objective=Objective(track=Track.ECOMMERCE, goal="...", success_patterns=[r"HTB\\{.*?\\}"]),
        url="https://target/",
    )

For finer control (custom LLM, custom browser, custom bandit) build the
components directly — see ``devdocs/05_feedback_engine_design.md``.
"""

from __future__ import annotations

from jb_ape.browser import BrowserClient, DryRunBrowserClient
from jb_ape.generator import Generator, RunConfig
from jb_ape.judge import Judge
from jb_ape.llm import LLMClient
from jb_ape.models import Objective
from jb_ape.planner import Bandit, Planner
from jb_ape.rewriter import Rewriter


def build_engine(
    objective: Objective,
    browser: BrowserClient | None = None,
    generator_llm: LLMClient | None = None,
    judge_llm: LLMClient | None = None,
    config: RunConfig | None = None,
    armory_root: str | None = "armory",
    tech_keywords: list[str] | None = None,
    gate_llm: LLMClient | None = None,
) -> Generator:
    """Wire the full wisdom engine. ``generator_llm`` drives the rewriter;
    ``judge_llm`` drives tier-3 adjudication; ``gate_llm`` drives the TAP
    on-topic pruning gate (devdocs/12 §2.2). Keep them separate instances
    (devdocs/05 §3.3). Any may be None for offline/partial runs.

    ``armory_root`` enables signal persistence + seed/prior/chain loading
    (devdocs/armory/README.md). Pass None to disable. Track-specific
    ``tech_keywords`` tune the judge (devdocs/01 §2); defaults come from
    ``prompts.keywords_for_track``."""
    from jb_ape.armory import Armory
    from jb_ape.prompts import keywords_for_track

    if tech_keywords is None:
        tech_keywords = keywords_for_track(objective.track)
    armory = Armory(armory_root) if armory_root else None
    bandit = Bandit()
    planner = Planner(objective=objective, bandit=bandit, armory=armory)
    rewriter = Rewriter(objective=objective, llm=generator_llm)
    judge = Judge(objective=objective, llm=judge_llm, tech_keywords=tech_keywords)
    browser = browser or DryRunBrowserClient()
    return Generator(
        objective=objective, browser=browser, judge=judge,
        rewriter=rewriter, planner=planner, bandit=bandit,
        config=config or RunConfig(), armory=armory, gate_llm=gate_llm,
    )


def quick_run(
    objective: Objective,
    url: str,
    browser: BrowserClient | None = None,
    generator_llm: LLMClient | None = None,
    judge_llm: LLMClient | None = None,
    budget: int = 60,
    config: RunConfig | None = None,
    armory_root: str | None = "armory",
    tech_keywords: list[str] | None = None,
    gate_llm: LLMClient | None = None,
):
    """One-call convenience: build the engine and run it against ``url``."""
    gen = build_engine(
        objective, browser=browser,
        generator_llm=generator_llm, judge_llm=judge_llm, config=config,
        armory_root=armory_root, tech_keywords=tech_keywords, gate_llm=gate_llm,
    )
    return gen.run(url, budget=budget)
