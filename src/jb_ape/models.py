"""Core data models for the wisdom engine.

Plain ``dataclass`` + ``enum`` types — no heavy dependencies, so the whole
package stays import-safe for unit tests. The designs follow
``devdocs/01_objective_and_success_criteria.md`` (Objective / JudgeResult /
Feedback) and ``devdocs/02_threat_model_and_defense_layers.md`` (DefenseProfile).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Track(str, Enum):
    """Competition track. Bandit state is keyed per-track to avoid
    cross-contamination of technique rewards (see devdocs/05 §5.3)."""

    OFFICE = "office"
    ECOMMERCE = "ecommerce"
    CODING = "coding"


class DefenseLayer(str, Enum):
    """The three + one defense layers (devdocs/02 §1).
    Used by ``DefenseProfile`` and the judge's ``resistance_hit``."""

    L1 = "L1"        # input-side static keyword filter
    L2 = "L2"        # system-prompt hardening
    L3 = "L3"        # model alignment (weak in this competition)
    L1_OUT = "L1out"  # output-side keyword filter / redaction


# Identifier types — kept as plain str aliases for ergonomics + type safety.
TechniqueId = str   # e.g. "T-A1", see techniques.py / devdocs/07
ScenarioId = str    # e.g. "S-CODE", see scenarios.py
BypassId = str      # e.g. "B-I3", see defense.py / devdocs/03


@dataclass
class Objective:
    """What "winning" means for a given run (devdocs/01 §2).

    ``success_patterns`` are machine-checkable signals (regex / substrings)
    that lift a response straight to level S/A without an LLM judge call —
    the cheapest and most reliable path. ``track`` selects the playbook.
    """

    track: Track
    goal: str
    success_patterns: list[str] = field(default_factory=list)
    # Structured payloads whose hijack is a win even if not byte-exact: e.g. a
    # target SQL/JSON the model should reproduce. The judge uses PM/APM
    # (Rouge-L ≥ 0.9) on these (devdocs/13 §4.1, hijack.py).
    approx_payloads: list[str] = field(default_factory=list)
    # Higher bar when submission budget is tight (devdocs/01 §3).
    submit_max_false_positive_risk: float = 0.10

    def matches_success_pattern(self, text: str) -> str | None:
        """Return the matched pattern if any success pattern hits, else None."""
        import re

        for pat in self.success_patterns:
            try:
                if re.search(pat, text, re.IGNORECASE):
                    return pat
            except re.error:
                # Non-regex literal fallback
                if pat.lower() in text.lower():
                    return pat
        return None


@dataclass
class DefenseProfile:
    """Reconnaissance result describing the target's defense shape
    (devdocs/02 §7). Drives which bypass layer ``rewriter`` targets."""

    detected_layers: set[DefenseLayer] = field(default_factory=set)
    # e.g. {"refund", "steal", "password"} — reverse-engineered L1 wordlist
    l1_wordlist: set[str] = field(default_factory=set)
    l1out_redacts: bool = False  # does output-side redact raw secrets?
    agent_tools: list[str] = field(default_factory=list)
    system_prompt_leak: str = ""
    # True if recon detected a perplexity filter (devdocs/14 §4): high-PPL /
    # heavily-encoded inputs get blocked → engine should prefer readable
    # techniques over B-I2/B-I5 encoding bypasses.
    ppl_filter_active: bool = False

    def resistance(self) -> set[DefenseLayer]:
        """Layers currently believed to be active."""
        return set(self.detected_layers)


@dataclass
class Variant:
    """A single generated payload with provenance metadata.

    ``mutation_chain`` records the ordered list of bypass / technique ids
    applied, so the bandit can attribute reward to the right operators
    (devdocs/05 §4.1, devdocs/09 AutoDAN/GPTFuzzer)."""

    payload: str
    technique: TechniqueId = ""
    scenario: ScenarioId = ""
    bypasses: list[BypassId] = field(default_factory=list)
    mutation_chain: list[str] = field(default_factory=list)
    depth: int = 0


@dataclass
class SubmissionResult:
    """Data the browser engine must return after ``submit_payload``
    (devdocs/08 §3). Judge consumes these in priority order:
    api_responses > network_log > console_log > dom_text."""

    dom_text: str = ""
    api_responses: list[dict] = field(default_factory=list)
    network_log: list[dict] = field(default_factory=list)
    console_log: list[str] = field(default_factory=list)
    error: str | None = None
    submitted: bool = False

    def corpus(self) -> str:
        """Flatten all channels into one searchable text blob for keyword
        checks. API/ network evidence is prefixed so the judge can weight it."""
        parts: list[str] = []
        if self.api_responses:
            parts.append("[API] " + _stringify(self.api_responses))
        if self.network_log:
            parts.append("[NET] " + _stringify(self.network_log))
        if self.console_log:
            parts.append("[CON] " + "\n".join(self.console_log))
        if self.dom_text:
            parts.append("[DOM] " + self.dom_text)
        return "\n".join(parts)


def _stringify(obj: object) -> str:
    import json

    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(obj)


@dataclass
class JudgeResult:
    """Structured output of the judge (devdocs/05 §3.1).

    Replaces the old fragile ``"SUCCESS: True" in content`` substring match
    (ape.py:699). ``level`` follows the S/A/B/C scheme in devdocs/01 §1."""

    level: str  # "S" | "A" | "B" | "C"
    achieved: bool
    quality_score: int  # 0-100
    resistance_hit: set[DefenseLayer] = field(default_factory=set)
    refusal_type: str = "none"  # moralizing|policy|silent|partial|none
    evidence: str = ""
    improve_hint: str = ""
    false_positive_risk: float = 1.0

    @property
    def can_submit(self) -> bool:
        """Submission gate (devdocs/01 §3): achieved AND low FPR risk."""
        return self.achieved and self.false_positive_risk < 0.10


@dataclass
class Feedback:
    """Compact feedback handed from judge back to rewriter/planner.
    ``recommended_layers`` is the set of defense layers the rewriter should
    counter next (devdocs/05 §4.1)."""

    quality_score: int
    achieved: bool
    recommended_layers: set[DefenseLayer]
    improve_hint: str
    refusal_type: str = "none"
