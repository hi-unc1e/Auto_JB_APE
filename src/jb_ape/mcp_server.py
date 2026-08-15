"""MCP server — jb_ape as a tool for host agents (devdocs/17).

Async-job pattern over the stateful Engagement: the host LLM agent calls
``start_engagement`` → gets an id → ``step_engagement`` (a few rounds at a
time) → reads compact VERDICTS from ``status_engagement`` (the built-in judge
decides; the host consumes, never re-judges) → ``steer_engagement`` to guide →
``report_engagement`` for the artifact.

The LOGIC layer below is plain functions (unit-tested without fastmcp);
``build_server()`` wraps them as FastMCP tools (lazy import — optional dep).
Run: ``python -m jb_ape.mcp_server``.
"""

from __future__ import annotations

from jb_ape.catalog import SCENARIOS
from jb_ape.engagement import (
    EngagementSpec,
    create_engagement,
    get_engagement,
)

# ───────────────────────── logic layer (no deps) ─────────────────────────


def mcp_list_scenarios() -> list[dict]:
    return [
        {"sid": s.sid, "problem": s.problem, "track": s.track.value,
         "canary": s.canary, "hijack": s.hijack, "notes": s.notes}
        for s in SCENARIOS.values()
    ]


def mcp_start_engagement(url: str, scenario: str | None = None,
                          track: str = "office", goal: str | None = None,
                          adapter: str = "dryrun", llm_model: str | None = None,
                          llm_base_url: str | None = None,
                          budget: int = 20, max_rounds: int = 20,
                          planner_kind: str = "tree",
                          run_recon: bool = True, recon_budget: int = 6) -> dict:
    spec = EngagementSpec(
        url=url, scenario=scenario, track=track, goal=goal, adapter=adapter,
        llm_model=llm_model, llm_base_url=llm_base_url, budget=budget,
        max_rounds=max_rounds, planner_kind=planner_kind,
        run_recon=run_recon, recon_budget=recon_budget,
        armory_root="armory",
    )
    eng = create_engagement(spec)
    return eng.status()


def mcp_step_engagement(eid: str, rounds: int = 1) -> dict:
    return get_engagement(eid).step(rounds=rounds)


def mcp_status_engagement(eid: str) -> dict:
    return get_engagement(eid).status()


def mcp_steer_engagement(eid: str, hint: str,
                         disable: list[str] | None = None) -> dict:
    return get_engagement(eid).steer(hint, disable=disable)


def mcp_report_engagement(eid: str) -> dict:
    eng = get_engagement(eid)
    return {"id": eid, "markdown": eng.report_md()}


def mcp_stop_engagement(eid: str) -> dict:
    eng = get_engagement(eid)
    eng.ctx.finished = True
    eng.save()
    return eng.status()


# ───────────────────────── FastMCP wiring (optional dep) ─────────────────────────


def build_server():  # pragma: no cover — requires fastmcp at runtime
    from fastmcp import FastMCP

    mcp = FastMCP("jb_ape_redteam")

    @mcp.tool()
    def list_scenarios() -> str:
        """List the 12 preset red-team problem scenarios (sid/problem/track)."""
        import json

        return json.dumps(mcp_list_scenarios(), ensure_ascii=False)

    @mcp.tool()
    def start_engagement(url: str, scenario: str | None = None,
                         track: str = "office", goal: str | None = None,
                         adapter: str = "dryrun",
                         llm_model: str | None = None,
                         llm_base_url: str | None = None,
                         budget: int = 20, max_rounds: int = 20,
                         planner_kind: str = "tree",
                         run_recon: bool = True, recon_budget: int = 6) -> str:
        """Start a stateful red-team engagement; returns the verdict status
        incl. engagement id. Authorized targets only. run_recon=False skips
        the defense-probing phase (attacks blind, saves budget)."""
        import json

        return json.dumps(mcp_start_engagement(
            url, scenario, track, goal, adapter, llm_model, llm_base_url,
            budget, max_rounds, planner_kind, run_recon, recon_budget),
            ensure_ascii=False)

    @mcp.tool()
    def step_engagement(eid: str, rounds: int = 1) -> str:
        """Advance the engagement by N generator rounds; returns the verdict."""
        import json

        return json.dumps(mcp_step_engagement(eid, rounds), ensure_ascii=False)

    @mcp.tool()
    def status_engagement(eid: str) -> str:
        """Read the compact verdict (level/score/evidence) — consume, do not
        re-judge; the engagement carries its own adjudicator."""
        import json

        return json.dumps(mcp_status_engagement(eid), ensure_ascii=False)

    @mcp.tool()
    def steer_engagement(eid: str, hint: str,
                         disable: list[str] | None = None) -> str:
        """Inject operator guidance; rides as [operator context] on subsequent
        test cases. Optionally disable technique ids (e.g. T-F1) — removed
        from routing until the engagement restarts."""
        import json

        return json.dumps(mcp_steer_engagement(eid, hint, disable=disable),
                          ensure_ascii=False)

    @mcp.tool()
    def report_engagement(eid: str) -> str:
        """Full markdown report of the engagement."""
        return mcp_report_engagement(eid)["markdown"]

    @mcp.tool()
    def stop_engagement(eid: str) -> str:
        """Mark the engagement finished (state snapshot retained)."""
        import json

        return json.dumps(mcp_stop_engagement(eid), ensure_ascii=False)

    return mcp


def main() -> None:  # pragma: no cover
    build_server().run()


if __name__ == "__main__":  # pragma: no cover
    main()
