"""Generation → parse → self-check → submission funnel (signal #20).

Every candidate the engine considers passes through a measurable funnel:

    generated → dedup → self-check → on-topic gate → submitted → judged → hits

Producers: ``Generator.step_round`` increments a ``Funnel`` carried on
``RunCtx`` at each stage. Consumer: ``RunReport.funnel`` (and the
``render_report`` funnel line) — the with/without contract lives in
``tests/test_signal_contracts.py`` (contract 20). A counter nobody reads is
dead instrumentation; the report IS the read.

The self-check stage is deliberately STRUCTURAL, not semantic: empty or
oversized bodies, pure code-fence husks, and bare refusals are dropped before
they burn a submission. Semantics stay with the on-topic gate and the judge.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

_FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*\n?(.*?)```", re.DOTALL)
_REFUSAL_RE = re.compile(
    r"^\s*(i\s+can(?:not|'|no)?t|i'?m\s+sorry|sorry[,.\s]+i|as\s+an\s+ai)\b",
    re.IGNORECASE,
)

MIN_PAYLOAD_CHARS = 8
MAX_PAYLOAD_CHARS = 6000


@dataclass
class Funnel:
    """Stage counters for one run. All monotonic; snapshot for the report."""

    generated: int = 0
    dedup_dropped: int = 0
    selfcheck_dropped: int = 0
    gate_dropped: int = 0
    budget_capped: int = 0
    submitted: int = 0
    judged: int = 0
    hits: int = 0

    def snapshot(self) -> dict[str, int]:
        return dict(asdict(self))


def effective_text(raw: str) -> str:
    """The payload text after stripping LLM packaging (parse stage).

    Handles the two artifacts a chatty rewriter leaves behind: surrounding
    code fences (keeps the fenced body, drops the husk) and outer quote
    wrappers. Never mutates real payloads — a clean string returns itself.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    m = _FENCE_RE.search(text)
    if m:
        body = m.group(1).strip()
        rest = (text[: m.start()] + text[m.end() :]).strip()
        if body:
            # fenced payload, possibly with chatter around it: keep the body
            return body if len(rest) < len(body) else text
        if not rest:
            return ""  # fence husk: fences with nothing inside
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'", "“", "”"}:
        return text[1:-1].strip()
    return text


def self_check(payload: str, *, min_chars: int = MIN_PAYLOAD_CHARS,
               max_chars: int = MAX_PAYLOAD_CHARS) -> tuple[bool, str]:
    """Structural sanity gate. Returns ``(ok, reason)`` — reason is empty
    when ok, human-readable when dropped."""
    text = effective_text(payload)
    if not text:
        return False, "empty"
    if len(text) < min_chars:
        return False, "too_short"
    if len(text) > max_chars:
        return False, "too_long"
    if not re.search(r"[0-9A-Za-z\u4e00-\u9fff]", text):
        return False, "no_content"  # punctuation/fence husk only
    if _REFUSAL_RE.match(text):
        return False, "refusal_leakage"  # rewriter echoed a refusal as payload
    return True, ""
