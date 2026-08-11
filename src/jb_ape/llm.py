"""LLM client abstraction.

The engine talks only to the ``LLMClient`` protocol. Real backends (OpenAI,
langchain) are thin adapters — and tests use a trivial in-process fake. This
keeps the package import-light (no langchain needed to ``import jb_ape``) and
makes every planner/rewriter/judge path unit-testable offline.
"""

from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    """Minimal chat interface used by rewriter/planner/judge."""

    def chat(self, system: str, user: str) -> str: ...


class EchoLLM:
    """Trivial fake client for tests. Returns a fixed canned response or echoes
    the user prompt. Never makes a network call."""

    def __init__(self, canned: str | None = None) -> None:
        self.canned = canned
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.canned if self.canned is not None else user


class ScriptedLLM:
    """Fake client that returns scripted responses in sequence. Useful for
    multi-step tests (planner → rewriter → judge)."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if not self._responses:
            return ""
        return self._responses.pop(0)


class OpenAICompatibleLLM:
    """Adapter for any OpenAI-compatible Chat Completions endpoint
    (OpenAI, OpenRouter, DeepSeek, local vLLM, …). Constructed lazily so the
    optional dependency is only required when this adapter is actually used.

    Reads ``OPENAI_API_KEY`` / ``OPENAI_BASE_URL`` from the environment.
    """

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.0,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout

    def chat(self, system: str, user: str) -> str:
        import os

        from openai import OpenAI  # imported lazily — optional dep

        client = OpenAI(
            api_key=self.api_key or os.getenv("OPENAI_API_KEY"),
            base_url=self.base_url or os.getenv("OPENAI_BASE_URL"),
            timeout=self.timeout,
        )
        resp = client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""
