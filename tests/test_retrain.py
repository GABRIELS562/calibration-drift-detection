"""Tests for the drift-triggered retraining decision."""

from pathlib import Path

import mlflow
import pytest

from drift.registry import PENDING, production_version
from drift.retrain import TriggerDecision, should_retrain, train_candidate_for_batch
from drift.train import MODEL_NAME
from drift.westgard import (
    ChartEvaluation,
    Rule,
    SensorVerdict,
    Verdict,
    WestgardResult,
)


def _result(batch: int, rejected: list[str], warned: list[str]) -> WestgardResult:
    sensors = []
    for s in rejected:
        trig = ChartEvaluation(gas=6, column=f"{s}_f1", z=-3.4, rules=frozenset({Rule.R_1_3S}))
        sensors.append(SensorVerdict(s, Verdict.REJECT, (trig,)))
    for s in warned:
        trig = ChartEvaluation(gas=4, column=f"{s}_f1", z=-1.6, rules=frozenset({Rule.R_4_1S}))
        sensors.append(SensorVerdict(s, Verdict.WARN, (trig,)))
    sensors.append(SensorVerdict("s16", Verdict.IN_CONTROL, ()))
    return WestgardResult(1, batch, tuple(range(2, batch)), tuple(sensors))


def test_no_rejected_sensors_does_not_trigger() -> None:
    decision = should_retrain(_result(5, rejected=[], warned=["s01", "s02"]))

    assert decision.triggered is False
    assert "warn" in decision.reason


def test_any_rejected_sensor_triggers() -> None:
    decision = should_retrain(_result(7, rejected=["s01", "s10"], warned=["s02"]))

    assert decision.triggered is True
    assert decision.rejected_sensors == ("s01", "s10")
    assert "batch 7" in decision.reason and "s01" in decision.reason


def test_trigger_reason_names_the_rule_and_analyte() -> None:
    decision = should_retrain(_result(8, rejected=["s09"], warned=[]))

    assert "1_3s" in decision.reason
    assert "toluene" in decision.reason


def test_decision_is_immutable() -> None:
    decision = should_retrain(_result(8, rejected=["s09"], warned=[]))

    with pytest.raises(AttributeError):
        decision.triggered = False  # type: ignore[misc]
    assert isinstance(decision, TriggerDecision)


def test_candidate_is_registered_pending_and_nothing_is_promoted(
    synthetic_batch, tmp_path: Path
) -> None:
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'mlflow.db'}")
    reference = synthetic_batch
    current = synthetic_batch.assign(batch=4)
    decision = should_retrain(_result(4, rejected=["s07"], warned=[]))

    version = train_candidate_for_batch(
        decision, reference=reference, history=[], current=current, dataset_sha256="beef"
    )

    mv = mlflow.MlflowClient().get_model_version(MODEL_NAME, version)
    assert mv.tags["approval_status"] == PENDING
    assert "s07" in mv.tags["trigger"]
    assert mv.tags["comparison"]
    assert production_version() is None


def test_candidate_not_trained_when_not_triggered(synthetic_batch, tmp_path: Path) -> None:
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'mlflow.db'}")
    decision = should_retrain(_result(3, rejected=[], warned=[]))

    with pytest.raises(ValueError, match="not triggered"):
        train_candidate_for_batch(
            decision,
            reference=synthetic_batch,
            history=[],
            current=synthetic_batch.assign(batch=3),
            dataset_sha256="beef",
        )
