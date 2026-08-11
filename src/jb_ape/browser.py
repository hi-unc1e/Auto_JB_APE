"""Browser engine contract + dry-run client (devdocs/08).

The real browser automation (agent-browser CLI / Browser Use plugin) is driven
by *another* engine and is **not implemented here** (devdocs/08 §1). This module
only:

1. Defines the ``BrowserClient`` protocol the generator depends on.
2. Provides a ``DryRunBrowserClient`` so the whole wisdom engine is testable
   offline (the user's explicit "先离线构建框架" requirement).

An external engine implements ``BrowserClient`` and injects it into
``Generator``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

from jb_ape.models import SubmissionResult


class BrowserClient(Protocol):
    """Contract between the wisdom engine and a browser backend
    (devdocs/08 §2). Implementations: agent-browser CLI wrapper, ZCode
    browser-use plugin, or ``DryRunBrowserClient`` for tests."""

    def open(self, url: str, *, session_id: str | None = None) -> None: ...

    def snapshot_interactive(self) -> str: ...
    def fill(self, ref: str, text: str) -> None: ...
    def click(self, ref: str) -> None: ...
    def press(self, key: str) -> None: ...
    def wait(self, spec: str) -> None: ...

    def submit_payload(self, payload: str, *, dry_run: bool = False) -> SubmissionResult: ...
    def get_dom_text(self) -> str: ...
    def get_api_responses(self) -> list[dict]: ...
    def get_network_log(self) -> list[dict]: ...
    def get_console_log(self) -> list[str]: ...
    def confirm_submit(self) -> None: ...


@dataclass
class DryRunBrowserClient:
    """Offline, hermetic client for tests / "build the framework first" mode.

    ``responses`` is a queue of ``SubmissionResult`` returned in order per
    ``submit_payload`` call (so tests can script a refusal then a success).
    Records every call for assertions.
    """

    responses: list[SubmissionResult] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    opened_urls: list[str] = field(default_factory=list)
    fills: list[tuple[str, str]] = field(default_factory=list)
    clicks: list[str] = field(default_factory=list)
    confirmed: int = 0

    def open(self, url: str, *, session_id: str | None = None) -> None:
        self.opened_urls.append(url)
        self.calls.append({"op": "open", "url": url, "session_id": session_id})

    def snapshot_interactive(self) -> str:
        return "@e1 [textarea] placeholder=\"Input\"\n@e2 [button] \"Submit\""

    def fill(self, ref: str, text: str) -> None:
        self.fills.append((ref, text))
        self.calls.append({"op": "fill", "ref": ref, "text": text})

    def click(self, ref: str) -> None:
        self.clicks.append(ref)
        self.calls.append({"op": "click", "ref": ref})

    def press(self, key: str) -> None:
        self.calls.append({"op": "press", "key": key})

    def wait(self, spec: str) -> None:
        self.calls.append({"op": "wait", "spec": spec})

    def submit_payload(self, payload: str, *, dry_run: bool = False) -> SubmissionResult:
        self.calls.append({"op": "submit", "payload": payload, "dry_run": dry_run})
        if self.responses:
            return self.responses.pop(0)
        return SubmissionResult(dom_text="(dry-run) no response queued", submitted=not dry_run)

    def get_dom_text(self) -> str:
        return "(dry-run) dom"

    def get_api_responses(self) -> list[dict]:
        return []

    def get_network_log(self) -> list[dict]:
        return []

    def get_console_log(self) -> list[str]:
        return []

    def confirm_submit(self) -> None:
        self.confirmed += 1
        self.calls.append({"op": "confirm"})


# --- agent-browser CLI helper (reference, not required) --------------------------

_AGENT_BROWSER_FLAGS = {
    "open": "open <url> [--session NAME]",
    "snapshot": "snapshot -i   # interactive-only accessibility tree",
    "fill": 'fill @eN "text"',
    "click": "click @eN",
    "press": "press Enter",
    "wait": 'wait --url "**/dash" | wait --text "ok" | wait --load networkidle',
    "get": "get text | get html",
}


def agent_browser_cheatsheet() -> str:
    """Return a compact cheatsheet of the agent-browser CLI commands the
    external backend may use (devdocs/08 §6). Reference only — not invoked."""
    return json.dumps(_AGENT_BROWSER_FLAGS, indent=2, ensure_ascii=False)
