"""Armory loader — persists and recalls red-team signals (armory/README.md).

The armory is the engine's long-term memory across runs and tracks:
* ``seeds/*.yml``   — curated payload seeds per track (devdocs/07, devdocs/06)
* ``priors/*.yml``  — literature-derived bandit priors (devdocs/09)
* ``findings/*.yml``— validated effective chains, promoted from run logs
* ``runs/*.jsonl``  — append-only run logs (every judged payload)

Design: YAML is optional. If PyYAML isn't installed, loaders return empty
defaults so the engine still runs (and unit tests stay hermetic). The run-log
writer uses stdlib json only — never YAML — so the "signal persistence" path
has zero optional deps.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jb_ape.models import Track, Variant


def _yaml() -> Any:
    """Import PyYAML lazily; return None if unavailable."""
    try:
        import yaml  # type: ignore[import-untyped]

        return yaml
    except ImportError:
        return None


@dataclass
class SeedEntry:
    """One curated payload seed from armory/seeds/*.yml."""

    sid: str
    name: str
    category: str
    payload: str
    layers: list[str] = field(default_factory=list)
    technique: str = ""
    notes: str = ""

    def to_variant(
        self, goal: str, depth: int = 0, placeholders: dict | None = None
    ) -> Variant:
        """Render the seed into a Variant, substituting {goal} and any extra
        placeholders (pi review P1-3).

        ``placeholders`` fills seed-specific tokens like {callback}, {tool},
        {secret}. Default safe values are used if a placeholder isn't supplied,
        so seeds never ship with literal ``{callback}`` text."""
        body = self.payload.replace("{goal}", goal)
        defaults = {
            "callback": "http://attacker-cb.example/",
            "tool": "send_email",
            "SECRET": "<SECRET>",
            "secret": "<SECRET>",
            "secret_encoded": "c2VjcmV0",  # base64("secret")
            "AMOUNT": "5000",
            "ATTACKER_IBAN": "GB00EXPT00000000000000",
            "ATTACKER_EMAIL": "audit@attacker-cb.example",
            "target_user": "1",
            "order_id": "1",
            "date": "2026-01-01",
        }
        if placeholders:
            defaults.update(placeholders)
        for key, val in defaults.items():
            body = body.replace("{" + key + "}", str(val))
        return Variant(
            payload=body,
            technique=self.technique or self.sid,
            scenario="",
            bypasses=[layer for layer in self.layers if layer.startswith("B-")],
            mutation_chain=[self.sid],
            depth=depth,
        )


@dataclass
class EffectiveChain:
    """A validated sequence of techniques/bypasses (armory/findings)."""

    cid: str
    name: str
    tracks: list[str]
    target_layers: list[str]
    sequence: list[str]
    description: str = ""
    asr_prior: float = 0.5


class Armory:
    """Read/write access to the armory. Construct with the armory root path."""

    def __init__(self, root: str | Path = "armory") -> None:
        self.root = Path(root)

    # -- seeds -------------------------------------------------------------------

    def load_seeds(self, track: Track | str | None = None) -> list[SeedEntry]:
        """Load seeds for a track (or all). Falls back to [] without PyYAML."""
        y = _yaml()
        if y is None:
            return []
        track_name = track.value if isinstance(track, Track) else track
        seeds_dir = self.root / "seeds"
        files = sorted(seeds_dir.glob("*.yml")) if seeds_dir.is_dir() else []
        out: list[SeedEntry] = []
        for fp in files:
            stem = fp.stem  # office / ecommerce / coding / general
            if track_name and stem != track_name and stem != "general":
                continue
            try:
                data = y.safe_load(fp.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                continue
            for item in data.get("seeds", []):
                out.append(_parse_seed(item))
        return out

    # -- priors ------------------------------------------------------------------

    def load_priors(self, track: Track | str | None = None) -> dict[str, tuple[float, float]]:
        """Load bandit priors as {arm_id: (alpha, beta)}.
        Merges ``default`` with the track-specific override."""
        y = _yaml()
        if y is None:
            return {}
        fp = self.root / "priors" / "technique_priors.yml"
        if not fp.is_file():
            return {}
        try:
            data = y.safe_load(fp.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            return {}
        merged: dict[str, tuple[float, float]] = {}
        for arm_id, pair in (data.get("default") or {}).items():
            merged[arm_id] = _to_pair(pair)
        if track is not None:
            tk = track.value if isinstance(track, Track) else track
            for arm_id, pair in (data.get(tk) or {}).items():
                merged[arm_id] = _to_pair(pair)
        return merged

    # -- findings ----------------------------------------------------------------

    def load_chains(self, track: Track | str | None = None) -> list[EffectiveChain]:
        """Load effective chains, optionally filtered by track."""
        y = _yaml()
        if y is None:
            return []
        fp = self.root / "findings" / "effective_chains.yml"
        if not fp.is_file():
            return []
        try:
            data = y.safe_load(fp.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            return []
        tk = track.value if isinstance(track, Track) else track
        out = []
        for item in data.get("chains", []):
            chain = _parse_chain(item)
            if tk is None or tk in chain.tracks or not chain.tracks:
                out.append(chain)
        return out

    # -- triggers (B-P1, devdocs/13) ---------------------------------------------

    def load_triggers(self) -> dict[str, dict]:
        """Load the universal-trigger library (armory/triggers.yml).

        Each entry: ``{model_family: {trigger1, trigger2, self_asr, transfers_to}}``.
        These are WHITE-BOX artifacts (GCG-trained on an open-source model).
        The engine consumes them for the B-P1 trigger-wrap bypass — but only
        against targets whose model family recon matches a library entry.
        Returns ``{}`` (hand-crafted fallback used) if the file is absent."""
        y = _yaml()
        if y is None:
            return {}
        fp = self.root / "triggers.yml"
        if not fp.is_file():
            return {}
        try:
            data = y.safe_load(fp.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def trigger_for(self, model_family: str | None) -> tuple[str, str] | None:
        """Look up a (trigger1, trigger2) pair for a recon-detected model family.
        Returns None if no trained trigger is available (caller falls back to
        the hand-crafted B-P1 baseline)."""
        if not model_family:
            return None
        lib = self.load_triggers()
        entry = lib.get(model_family)
        if not entry:
            return None
        t1 = str(entry.get("trigger1", ""))
        t2 = str(entry.get("trigger2", ""))
        if not t1:
            return None
        return t1, t2

    # -- run log (signal persistence, zero-dep) ---------------------------------

    def log_finding(self, track: Track, record: dict, run_id: str | None = None) -> Path:
        """Append a judged payload record to runs/<run_id>.jsonl.
        This is the core 'persist every signal' path — never raises into the run."""
        run_id = run_id or time.strftime("%Y%m%d_%H%M%S")
        runs_dir = self.root / "runs"
        try:
            runs_dir.mkdir(parents=True, exist_ok=True)
            fp = runs_dir / f"{run_id}_{track.value}.jsonl"
            line = json.dumps({"ts": time.time(), "track": track.value, **record},
                              ensure_ascii=False)
            # Use a context manager so the handle is always closed (no
            # ResourceWarning leak — the user demanded zero low-level errors).
            with fp.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            return fp
        except OSError:
            # Persistence is best-effort; never break the run over logging.
            return Path("/dev/null")


# --- parse helpers ---------------------------------------------------------------


def _parse_seed(item: dict) -> SeedEntry:
    return SeedEntry(
        sid=str(item.get("id", "")),
        name=str(item.get("name", "")),
        category=str(item.get("category", "")),
        payload=str(item.get("payload", "")),
        layers=list(item.get("layers", []) or []),
        technique=str(item.get("technique", "")),
        notes=str(item.get("notes", "")),
    )


def _parse_chain(item: dict) -> EffectiveChain:
    return EffectiveChain(
        cid=str(item.get("id", "")),
        name=str(item.get("name", "")),
        tracks=list(item.get("tracks", []) or []),
        target_layers=list(item.get("target_layers", []) or []),
        sequence=list(item.get("sequence", []) or []),
        description=str(item.get("description", "")),
        asr_prior=float(item.get("asr_prior", 0.5)),
    )


def _to_pair(val: Any) -> tuple[float, float]:
    """Coerce a yaml list [a, b] into a (alpha, beta) tuple."""
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        return float(val[0]), float(val[1])
    return 1.0, 1.0
