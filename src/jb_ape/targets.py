"""Real target adapters — makes jb_ape runnable against live targets.

Two adapters implement the ``BrowserClient`` protocol (devdocs/08):

* ``AgentBrowserClient`` — drives the locally-installed ``agent-browser`` CLI
  (vercel-labs; snapshot/ref model). Command *construction* is pure and
  unit-tested; *execution* is subprocess-based and only happens live.
* ``LLMTargetClient`` — treats any OpenAI-compatible chat endpoint as the
  target (many agent red-team targets are APIs, not browsers). Keeps a
  per-session multi-turn history; the model's reply lands in
  ``api_responses`` (the judge's highest-trust channel). A ``transport``
  callable can be injected for hermetic testing.

Neither adapter is imported by the engine by default — the offline
``DryRunBrowserClient`` stays the default so unit tests stay hermetic.
"""

from __future__ import annotations

import json
import subprocess

from jb_ape.models import SubmissionResult

# ────────────────────────── agent-browser CLI adapter ─────────────────────────

class AgentBrowserClient:
    """BrowserClient backed by the ``agent-browser`` CLI.

    Uses the snapshot→ref workflow (devdocs/08 §5.1): refs are invalidated by
    page changes, so every submit re-snapshots before acting."""

    def __init__(self, binary: str = "agent-browser", session: str | None = None,
                 timeout: float = 60.0) -> None:
        self.binary = binary
        self.session = session
        self.timeout = timeout
        self.confirmed = 0

    # -- execution ------------------------------------------------------------
    def _run(self, args: list[str]) -> str:
        cmd = [self.binary, *args]
        if self.session and args and args[0] not in ("--session",):
            cmd = [self.binary, "--session", self.session, *args]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"agent-browser {args[:2]} failed: {proc.stderr[:200]}")
        return proc.stdout

    # -- pure command construction (unit-tested without executing) -----------
    @staticmethod
    def build_wait_args(spec: str) -> list[str]:
        """"load networkidle" → ["--load","networkidle"]; "url **/x" → --url; "text ok" → --text."""
        kind, _, value = spec.partition(" ")
        kind = kind.strip().lower()
        if kind == "load":
            return ["--load", value.strip()]
        if kind == "url":
            return ["--url", value.strip()]
        if kind == "text":
            return ["--text", value.strip()]
        return ["--load", "networkidle"]

    @staticmethod
    def find_input_ref(snapshot: str) -> str:
        """First interactive text-input ref from a snapshot tree (@eN lines)."""
        for line in snapshot.splitlines():
            low = line.lower()
            if ("[textarea]" in low or "[input" in low or "textbox" in low) \
                    and "@" in line:
                return line.split("@")[1].split()[0].rstrip("]")
        return "@e1"  # heuristic default

    @staticmethod
    def find_submit_ref(snapshot: str) -> str:
        for line in snapshot.splitlines():
            low = line.lower()
            if ("[button]" in low or "submit" in low) and "@" in line:
                return line.split("@")[1].split()[0].rstrip("]")
        return "@e2"

    @staticmethod
    def build_submit_sequence(payload: str, snapshot: str) -> list[list[str]]:
        """The argv sequence a submit performs (pure; asserted in tests)."""
        input_ref = AgentBrowserClient.find_input_ref(snapshot)
        submit_ref = AgentBrowserClient.find_submit_ref(snapshot)
        return [
            ["fill", input_ref, payload],
            ["click", submit_ref],
            ["wait", *AgentBrowserClient.build_wait_args("load networkidle")],
        ]

    # -- BrowserClient protocol ------------------------------------------------
    def open(self, url: str, *, session_id: str | None = None) -> None:
        if session_id:
            self.session = session_id
        self._run(["open", url])

    def snapshot_interactive(self) -> str:
        return self._run(["snapshot", "-i"])

    def fill(self, ref: str, text: str) -> None:
        self._run(["fill", ref, text])

    def click(self, ref: str) -> None:
        self._run(["click", ref])

    def press(self, key: str) -> None:
        self._run(["press", key])

    def wait(self, spec: str) -> None:
        self._run(["wait", *self.build_wait_args(spec)])

    def submit_payload(self, payload: str, *, dry_run: bool = False) -> SubmissionResult:
        snap = self.snapshot_interactive()
        for args in self.build_submit_sequence(payload, snap):
            self._run(args)
        dom = ""
        err = None
        try:
            dom = self._run(["get", "text"])
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            err = str(exc)
        net: list[dict] = []
        try:  # network capture is best-effort; flag availability varies by CLI version
            raw = self._run(["network-requests", "--json"])
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                net = [e for e in parsed if isinstance(e, dict)]
        except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        return SubmissionResult(dom_text=dom, network_log=net, error=err,
                                 submitted=not dry_run)

    def get_dom_text(self) -> str:
        try:
            return self._run(["get", "text"])
        except (RuntimeError, subprocess.TimeoutExpired):
            return ""

    def get_api_responses(self) -> list[dict]:
        return []

    def get_network_log(self) -> list[dict]:
        try:
            parsed = json.loads(self._run(["network-requests", "--json"]))
            return parsed if isinstance(parsed, list) else []
        except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return []

    def get_console_log(self) -> list[str]:
        return []

    def confirm_submit(self) -> None:
        self.confirmed += 1


# ────────────────────────── OpenAI-compatible API target ──────────────────────

class LLMTargetClient:
    """BrowserClient for an API target: each submit_payload = one chat turn.

    The reply is placed in ``api_responses`` — the judge's most-trusted
    channel — so success patterns / hijack / decode all operate on it. A
    ``transport(messages) -> str`` callable may be injected; the default
    lazily uses the ``openai`` package against ``base_url``."""

    def __init__(self, model: str, base_url: str | None = None,
                 api_key: str | None = None, system: str | None = None,
                 transport=None) -> None:
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.system = system
        self.transport = transport or self._default_transport
        self._histories: dict[str, list[dict]] = {}
        self._current: str | None = None
        self.confirmed = 0

    def _default_transport(self, messages: list[dict]) -> str:
        import os

        from openai import OpenAI  # lazy optional dep

        client = OpenAI(api_key=self.api_key or os.getenv("OPENAI_API_KEY"),
                        base_url=self.base_url or os.getenv("OPENAI_BASE_URL"))
        resp = client.chat.completions.create(
            model=self.model, temperature=0.7, messages=messages)
        return resp.choices[0].message.content or ""

    def _history(self, session_id: str | None) -> list[dict]:
        key = session_id or self._current or "default"
        if key not in self._histories:
            self._histories[key] = (
                [{"role": "system", "content": self.system}] if self.system else [])
        return self._histories[key]

    # -- BrowserClient protocol ------------------------------------------------
    def open(self, url: str, *, session_id: str | None = None) -> None:
        self._current = session_id or url  # url is only a session label here

    def snapshot_interactive(self) -> str:
        return "(api target: no DOM)"

    def fill(self, ref: str, text: str) -> None:  # pragma: no cover — no-op
        pass

    def click(self, ref: str) -> None:  # pragma: no cover — no-op
        pass

    def press(self, key: str) -> None:  # pragma: no cover — no-op
        pass

    def wait(self, spec: str) -> None:  # pragma: no cover — no-op
        pass

    def submit_payload(self, payload: str, *, dry_run: bool = False) -> SubmissionResult:
        history = self._history(None)
        history.append({"role": "user", "content": payload})
        try:
            reply = self.transport(list(history))
        except Exception as exc:  # noqa: BLE001 — target errors are evidence
            return SubmissionResult(error=f"target transport error: {exc}")
        history.append({"role": "assistant", "content": reply})
        return SubmissionResult(api_responses=[{"role": "assistant", "content": reply}],
                                 submitted=not dry_run)

    def get_dom_text(self) -> str:
        h = self._history(None)
        return h[-1]["content"] if h else ""

    def get_api_responses(self) -> list[dict]:
        h = self._history(None)
        return [m for m in h if m.get("role") == "assistant"]

    def get_network_log(self) -> list[dict]:
        return []

    def get_console_log(self) -> list[str]:
        return []

    def confirm_submit(self) -> None:
        self.confirmed += 1
