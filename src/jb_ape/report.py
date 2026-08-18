"""Human-readable run report (operator UX).

For a tight submission budget, you need to see at a glance: did we win,
what was the winning payload + mutation chain, where did recon say the defenses
were, and what's worth promoting to the armory. ``render_report`` formats a
``RunReport`` into a compact markdown string for the console / a log file.
"""

from __future__ import annotations

from jb_ape.generator import RunReport


def render_report(report: RunReport, url: str = "") -> str:
    """Render a RunReport as a compact markdown string."""
    lines: list[str] = []
    verdict = "✅ ACHIEVED" if report.achieved else "❌ NOT ACHIEVED"
    lines.append(f"# Run Report — {verdict}")
    lines.append("")
    lines.append(f"- Target: `{url or '(unknown)'}`")
    lines.append(f"- Rounds: {report.rounds} | Submissions: {report.submissions} "
                 f"(recon: {report.recon_cost}) | Confirmed: {report.confirmed}")

    # Recon summary (devdocs/02 §7)
    prof = report.recon_profile
    if prof is not None:
        layers = ", ".join(sorted(layer.value for layer in prof.resistance())) or "(none detected)"
        lines.append(f"- Recon: active defenses = {layers}")
        if getattr(prof, "l1out_redacts", False):
            lines.append("- Recon: ⚠️ L1' redacts raw output → output-side encoding required")
        if getattr(prof, "system_prompt_leak", ""):
            lines.append("- Recon: 🎯 system prompt leaked (L2 weak)")
        if getattr(prof, "agent_tools", []):
            lines.append(f"- Recon: agent tools = {', '.join(prof.agent_tools[:8])}")

    # Best result — the winning payload (or closest miss).
    if report.best is not None:
        b = report.best
        lines.append("")
        lines.append(f"## Best result — level {b.level}, score {b.score}/100"
                     + (" (CONFIRMED)" if b.confirmed else ""))
        lines.append(f"- arm: `{b.arm_id}`")
        lines.append(f"- mutation chain: `{' → '.join(b.variant.mutation_chain) or '(seed)'}`")
        lines.append("- payload:")
        for pl in b.variant.payload.splitlines() or ["(empty)"]:
            lines.append(f"  > {pl}")

    # Top 5 attempts by score — shows what worked / what to promote.
    if report.records:
        ranked = sorted(report.records, key=lambda r: r.score, reverse=True)[:5]
        lines.append("")
        lines.append("## Top attempts")
        for i, r in enumerate(ranked, 1):
            tag = "✅" if r.confirmed else ("🎯" if r.achieved else "  ")
            lines.append(f"{i}. {tag} [{r.level}] {r.score}/100 — `{r.arm_id}`"
                         f" chain=`{' → '.join(r.variant.mutation_chain) or 'seed'}`")

    # Promotion hints — B+ results worth lifting into armory/findings.
    promote = [r for r in report.records if r.level in {"S", "A", "B"}]
    if promote:
        lines.append("")
        lines.append(f"## {len(promote)} signal(s) persisted to armory/runs/")
        best_chain = max(promote, key=lambda r: r.score).variant.mutation_chain
        if best_chain and not report.achieved:
            lines.append(f"- 💡 consider promoting chain `{' → '.join(best_chain)}` "
                         "to armory/findings/effective_chains.yml")

    return "\n".join(lines)
