"""Append-only, hash-chained audit log.

Every drift evaluation, candidate registration, approval, rejection and
rollback is appended as one JSON line. Each entry carries the hash of the
entry before it, so removing, reordering or editing any entry breaks the
chain and ``verify_chain`` says which one. An audit trail that can be
edited without trace is not an audit trail (ADR-0005).

The file is only ever opened for append. Nothing in this module rewrites
an existing line.
"""

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

AUDIT_LOG_PATH: Final = Path(__file__).resolve().parents[2] / "audit" / "audit.jsonl"
GENESIS_HASH: Final = "0" * 64


class ChainError(RuntimeError):
    """The audit log does not verify: an entry was edited, removed or forged."""


@dataclass(frozen=True)
class AuditEvent:
    seq: int
    timestamp: str
    action: str
    actor: str
    details: dict[str, Any]
    prev_hash: str
    hash: str


def _digest(payload: dict[str, Any]) -> str:
    """Hash of everything except the hash field itself, with stable key order."""
    body = {k: v for k, v in payload.items() if k != "hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _read_raw(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append_event(path: Path, *, action: str, actor: str, details: dict[str, Any]) -> AuditEvent:
    """Append one event. Never modifies an existing entry."""
    if not action.strip():
        raise ValueError("action is required")
    if not actor.strip():
        raise ValueError("actor is required — every entry names who or what acted")
    json.dumps(details)  # fail here rather than writing a partial line

    existing = _read_raw(path)
    payload = {
        "seq": len(existing) + 1,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "action": action,
        "actor": actor,
        "details": details,
        "prev_hash": existing[-1]["hash"] if existing else GENESIS_HASH,
    }
    payload["hash"] = _digest(payload)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return AuditEvent(**payload)


def verify_chain(path: Path) -> int:
    """Verify every link. Returns the entry count, or raises ``ChainError``."""
    previous = GENESIS_HASH
    entries = _read_raw(path)
    for index, entry in enumerate(entries, start=1):
        if entry.get("seq") != index:
            raise ChainError(f"entry {index}: sequence is {entry.get('seq')}, expected {index}")
        if entry.get("prev_hash") != previous:
            raise ChainError(f"entry {index}: does not link to the previous entry")
        if entry.get("hash") != _digest(entry):
            raise ChainError(f"entry {index}: contents do not match its hash")
        previous = entry["hash"]
    return len(entries)


def read_events(path: Path) -> list[AuditEvent]:
    return [AuditEvent(**entry) for entry in _read_raw(path)]


def event_dicts(path: Path) -> list[dict[str, Any]]:
    return [asdict(e) for e in read_events(path)]
