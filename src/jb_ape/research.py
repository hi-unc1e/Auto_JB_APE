"""Private, source-grounded intake ledger for new red-team methods.

The ledger records a hypothesis and its source before any candidate can enter
the live seed/decision catalog. It deliberately does not turn a paper's ASR
claim into a runtime prior or activate payloads from untrusted source text.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

REQUIRED = (
    "source_url", "title", "author", "published_at", "source_kind",
    "trust_boundary", "surface", "preconditions", "mechanism",
    "decision_signal", "expected_behavior", "oracle", "negative_cases",
    "limitations", "novelty", "proposed_change", "snapshot_file",
)
CHANGES = {"knowledge", "seed", "decision_node", "new_range"}
SURFACES = {"user_prompt", "tool_return", "memory", "skill", "subagent_message"}
MAX_SNAPSHOT_BYTES = 25 * 1024 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _card_path(root: Path, card_id: str) -> Path:
    if not card_id.startswith("R-") or len(card_id) != 14 or any(
        c not in "0123456789abcdef" for c in card_id[2:]
    ):
        raise ValueError("invalid research card id")
    return root / "research" / "candidates" / f"{card_id}.json"


def _save(path: Path, card: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def intake(root: str | Path, draft_path: str | Path) -> dict:
    """Create an idempotent candidate and keep its exact source snapshot local."""
    root = Path(root)
    draft_path = Path(draft_path)
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED if not draft.get(key)]
    if missing:
        raise ValueError(f"missing research fields: {', '.join(missing)}")
    url = urlparse(str(draft["source_url"]))
    if url.scheme != "https" or not url.netloc:
        raise ValueError("source_url must be an HTTPS URL")
    if draft["source_kind"] not in {"paper", "blog", "report", "advisory"}:
        raise ValueError("source_kind must be paper, blog, report, or advisory")
    if draft["surface"] not in SURFACES:
        raise ValueError("unknown attack surface")
    if draft["proposed_change"] not in CHANGES:
        raise ValueError("unknown proposed change")
    if draft["proposed_change"] != "knowledge" and not draft.get("test_artifact_file"):
        raise ValueError("runtime candidates require test_artifact_file")
    source_path = Path(draft["snapshot_file"])
    if not source_path.is_absolute():
        source_path = draft_path.parent / source_path
    if not source_path.is_file():
        raise ValueError("snapshot_file does not exist")
    if source_path.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise ValueError("source snapshot exceeds 25 MiB")
    source_bytes = source_path.read_bytes()
    if not source_bytes:
        raise ValueError("source snapshot is empty")
    source_sha = _sha(source_bytes)
    identity = "\n".join((str(draft["source_url"]), source_sha,
                           str(draft["mechanism"]), str(draft["decision_signal"])))
    card_id = "R-" + _sha(identity.encode())[:12]
    path = _card_path(root, card_id)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    source_dir = root / "research" / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    saved_source = source_dir / source_sha
    if not saved_source.exists():
        with saved_source.open("xb") as handle:
            handle.write(source_bytes)
    card = {key: draft[key] for key in REQUIRED if key != "snapshot_file"}
    if draft.get("test_artifact_file"):
        artifact_path = Path(draft["test_artifact_file"])
        if not artifact_path.is_absolute():
            artifact_path = draft_path.parent / artifact_path
        if not artifact_path.is_file() or artifact_path.stat().st_size > MAX_SNAPSHOT_BYTES:
            raise ValueError("test_artifact_file missing or too large")
        artifact_bytes = artifact_path.read_bytes()
        if not artifact_bytes:
            raise ValueError("test_artifact_file is empty")
        artifact_sha = _sha(artifact_bytes)
        artifact_dir = root / "research" / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        saved_artifact = artifact_dir / artifact_sha
        if not saved_artifact.exists():
            with saved_artifact.open("xb") as handle:
                handle.write(artifact_bytes)
        card["test_artifact_sha256"] = artifact_sha
        card["test_artifact_snapshot"] = str(saved_artifact.relative_to(root))
    card.update({
        "id": card_id,
        "source_sha256": source_sha,
        "source_bytes": len(source_bytes),
        "source_snapshot": str(saved_source.relative_to(root)),
        "accessed_at": datetime.now(timezone.utc).isoformat(),
        "status": "candidate",
        "evidence": [],
        "decision": None,
    })
    _save(path, card)
    return card


def read_card(root: str | Path, card_id: str) -> dict:
    return json.loads(_card_path(Path(root), card_id).read_text(encoding="utf-8"))


def list_cards(root: str | Path) -> list[dict]:
    directory = Path(root) / "research" / "candidates"
    return [json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("R-*.json"))]


def attach_arena_evidence(
    root: str | Path, card_id: str, manifest: str | Path, arena_root: str | Path
) -> dict:
    """Attach both successes and failures; only a strict audited run is verified."""
    root = Path(root)
    manifest = Path(manifest).resolve()
    arena_root = Path(arena_root).resolve()
    if not manifest.is_file():
        raise ValueError("manifest does not exist")
    script = arena_root / "scripts" / "audit_asr_target.py"
    if not script.is_file():
        raise ValueError("AgentArena auditor not found")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(arena_root / "src")
    environment["AUTO_JB_APE_SRC"] = str(Path(__file__).resolve().parent.parent)
    try:
        audit = subprocess.run(
            [sys.executable, str(script), "--manifest", str(manifest), "--strict"],
            cwd=arena_root, env=environment, capture_output=True, text=True,
            timeout=120, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        audit = None
        report = {"verified": False, "errors": [f"auditor unavailable: {type(exc).__name__}"]}
    else:
        try:
            report = json.loads(audit.stdout)
        except json.JSONDecodeError:
            report = {"verified": False, "errors": ["auditor did not return JSON"]}
    card = read_card(root, card_id)
    matches = 0
    hits = 0
    if audit is not None and audit.returncode == 0 and report.get("verified") is True and card.get(
        "test_artifact_sha256"
    ):
        inventory = json.loads(manifest.read_text(encoding="utf-8"))
        for campaign in inventory.get("campaigns", []):
            record_path = (arena_root / campaign["file"]).resolve()
            if not record_path.is_relative_to(arena_root):
                raise ValueError("manifest record escapes Arena root")
            for line in record_path.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                lineage = record.get("metadata", {}).get("candidate_lineage") or {}
                if (lineage.get("candidate_sha256") == card["test_artifact_sha256"]
                        and lineage.get("surface") == card["surface"]):
                    matches += 1
                    metadata = record.get("metadata", {})
                    risk = metadata.get("risk_axes") or {}
                    delivery = metadata.get("delivery_axes") or {}
                    observed = bool(risk.get("exposure_seen"))
                    if metadata.get("protocol_version") == "arena-evidence-v3.1":
                        observed = observed and bool(delivery.get("artifact_observed"))
                    hits += int(observed and bool(risk.get("violation_attempt")))
    errors = list(report.get("errors") or [])[:10]
    if card.get("test_artifact_sha256") and matches == 0 and audit is not None and audit.returncode == 0:
        errors.append("candidate hash absent from audited Arena records")
    row = {
        "manifest": str(manifest), "sha256": _sha(manifest.read_bytes()),
        "verified": audit is not None and audit.returncode == 0 and report.get("verified") is True
                    and (not card.get("test_artifact_sha256") or matches > 0),
        "candidate_matches": matches,
        "candidate_hits": hits,
        "errors": errors,
        "attached_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _card_path(root, card_id)
    if not any(item["sha256"] == row["sha256"] for item in card["evidence"]):
        card["evidence"].append(row)
        _save(path, card)
    return row


def decide(root: str | Path, card_id: str, disposition: str, rationale: str) -> dict:
    """Record triage. Code activation remains a reviewed, tested change."""
    if disposition not in CHANGES | {"reject"}:
        raise ValueError("invalid disposition")
    if not rationale.strip():
        raise ValueError("a decision rationale is required")
    root = Path(root)
    path = _card_path(root, card_id)
    card = read_card(root, card_id)
    if disposition in {"seed", "decision_node", "new_range"} and not any(
        item["verified"] and item.get("candidate_hits", 0) > 0
        for item in card["evidence"]
    ):
        raise ValueError("runtime changes require a strict audited, candidate-linked Arena hit")
    card["decision"] = {
        "disposition": disposition, "rationale": rationale.strip(),
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    card["status"] = "rejected" if disposition == "reject" else "reviewed"
    _save(path, card)
    return card
