"""jb_ape — Automated LLM red-team payload wisdom engine.

A red-team research framework for generating, mutating, and
adjudicating prompt-injection / jailbreak payloads. See ``devdocs/`` for the
full knowledge base.

The package is intentionally dependency-light at import time: heavy optional
dependencies (langchain, langgraph, playwright) are only required for the
runtime entry points, so that unit tests and static analysis stay fast and
hermetic.
"""

from __future__ import annotations

from jb_ape.facade import build_engine, quick_run
from jb_ape.models import (
    BypassId,
    DefenseLayer,
    DefenseProfile,
    Feedback,
    JudgeResult,
    Objective,
    ScenarioId,
    SubmissionResult,
    TechniqueId,
    Track,
    Variant,
)
from jb_ape.qa import QAReport, build_qa_suite, qa_smoke_test

__all__ = [
    "BypassId",
    "DefenseLayer",
    "DefenseProfile",
    "Feedback",
    "JudgeResult",
    "Objective",
    "QAReport",
    "ScenarioId",
    "SubmissionResult",
    "TechniqueId",
    "Track",
    "Variant",
    "build_engine",
    "build_qa_suite",
    "qa_smoke_test",
    "quick_run",
    "__version__",
]

__version__ = "0.1.0"
