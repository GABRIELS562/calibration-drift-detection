"""Tests for the append-only, hash-chained audit log."""

import json
from pathlib import Path

import pytest

from drift.audit import (
    GENESIS_HASH,
    AuditEvent,
    ChainError,
    append_event,
    read_events,
    verify_chain,
)


@pytest.fixture
def log(tmp_path: Path) -> Path:
    return tmp_path / "audit.jsonl"


def test_first_event_links_to_genesis(log: Path) -> None:
    event = append_event(log, action="drift_evaluated", actor="ci", details={"batch": 3})

    assert event.seq == 1
    assert event.prev_hash == GENESIS_HASH
    assert len(event.hash) == 64


def test_events_chain_by_hash(log: Path) -> None:
    first = append_event(log, action="candidate_registered", actor="ci", details={"version": "2"})
    second = append_event(log, action="approved", actor="analyst", details={"version": "2"})

    assert second.seq == 2
    assert second.prev_hash == first.hash
    assert verify_chain(log) == 2


def test_appending_never_rewrites_earlier_lines(log: Path) -> None:
    append_event(log, action="a", actor="x", details={})
    first_line = log.read_text().splitlines()[0]

    append_event(log, action="b", actor="x", details={})

    assert log.read_text().splitlines()[0] == first_line
    assert len(log.read_text().splitlines()) == 2


def test_verify_detects_an_edited_entry(log: Path) -> None:
    append_event(log, action="approved", actor="analyst", details={"version": "2"})
    append_event(log, action="approved", actor="analyst", details={"version": "3"})
    lines = log.read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered["actor"] = "someone-else"
    log.write_text("\n".join([json.dumps(tampered), lines[1]]) + "\n")

    with pytest.raises(ChainError, match="entry 1"):
        verify_chain(log)


def test_verify_detects_a_deleted_entry(log: Path) -> None:
    for i in range(3):
        append_event(log, action="x", actor="a", details={"i": i})
    lines = log.read_text().splitlines()
    log.write_text(lines[0] + "\n" + lines[2] + "\n")

    with pytest.raises(ChainError, match="entry 2"):
        verify_chain(log)


def test_verify_detects_an_appended_forgery(log: Path) -> None:
    append_event(log, action="x", actor="a", details={})
    forged = {
        "seq": 2,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "action": "approved",
        "actor": "attacker",
        "details": {},
        "prev_hash": "0" * 64,
        "hash": "f" * 64,
    }
    with log.open("a") as fh:
        fh.write(json.dumps(forged) + "\n")

    with pytest.raises(ChainError, match="entry 2"):
        verify_chain(log)


def test_empty_log_verifies_as_zero_entries(log: Path) -> None:
    assert verify_chain(log) == 0


def test_read_events_returns_typed_events_in_order(log: Path) -> None:
    append_event(log, action="drift_evaluated", actor="ci", details={"batch": 7})
    append_event(log, action="candidate_registered", actor="ci", details={"version": "2"})

    events = read_events(log)

    assert [e.action for e in events] == ["drift_evaluated", "candidate_registered"]
    assert all(isinstance(e, AuditEvent) for e in events)
    assert events[0].details["batch"] == 7


def test_details_must_be_json_serialisable(log: Path) -> None:
    with pytest.raises(TypeError):
        append_event(log, action="x", actor="a", details={"bad": object()})


def test_action_and_actor_are_required(log: Path) -> None:
    for kwargs in ({"action": "", "actor": "a"}, {"action": "x", "actor": " "}):
        with pytest.raises(ValueError):
            append_event(log, details={}, **kwargs)


def test_no_test_may_write_to_the_real_audit_log(isolate_audit_log) -> None:
    """Regression guard: the autouse fixture must redirect every binding."""
    from drift import pipeline, registry, train
    from drift.audit import AUDIT_LOG_PATH as module_path

    bindings = (module_path, registry.AUDIT_LOG_PATH, train.AUDIT_LOG_PATH, pipeline.AUDIT_LOG_PATH)
    for path in bindings:
        assert path == isolate_audit_log
        assert "calibration-drift-detection/audit/audit.jsonl" not in str(path)
