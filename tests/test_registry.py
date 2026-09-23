"""Tests for the approval gate and rollback over the MLflow registry."""

from pathlib import Path

import mlflow
import pytest

from drift.registry import (
    APPROVED,
    NO_INCUMBENT,
    PENDING,
    PRODUCTION_ALIAS,  # noqa: F401
    REJECTED,
    ApprovalError,
    approve,
    audit_trail,
    production_version,
    register_candidate,
    reject,
    rollback,
)
from drift.train import MODEL_NAME, fit_baseline, split_features_labels


@pytest.fixture
def registry(synthetic_batch, tmp_path: Path):
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'mlflow.db'}")
    x, y = split_features_labels(synthetic_batch)
    model = fit_baseline(x, y, seed=1)
    return model, x


def _register(model, x, **kw):
    defaults = dict(
        metrics={"accuracy": 0.9, "f1_macro": 0.9},
        incumbent_metrics={"accuracy": 0.95, "f1_macro": 0.95},
        params={"seed": 1},
        dataset_sha256="cafe",
        trigger="batch4: sensors s01,s02 rejected",
        example=x.head(2),
    )
    return register_candidate(model, **{**defaults, **kw})


def test_candidate_registers_as_pending_not_production(registry) -> None:
    model, x = registry

    version = _register(model, x, metrics={"accuracy": 0.99, "f1_macro": 0.99})

    mv = mlflow.MlflowClient().get_model_version(MODEL_NAME, version)
    assert mv.tags["approval_status"] == PENDING
    assert mv.tags["trigger"] == "batch4: sensors s01,s02 rejected"
    assert production_version() is None  # nothing promoted itself


def test_worse_candidate_is_still_registered_with_its_reason(registry) -> None:
    model, x = registry

    version = _register(model, x, metrics={"accuracy": 0.80, "f1_macro": 0.75})

    mv = mlflow.MlflowClient().get_model_version(MODEL_NAME, version)
    assert mv.tags["approval_status"] == PENDING
    assert "f1_macro" in mv.tags["comparison"]
    assert mv.tags["regression"] == "true"


def test_no_incumbent_is_recorded_explicitly_not_left_blank(registry) -> None:
    model, x = registry

    version = _register(model, x, incumbent_metrics={})

    mv = mlflow.MlflowClient().get_model_version(MODEL_NAME, version)
    assert mv.tags["comparison"] == NO_INCUMBENT
    assert mv.tags["regression"] == "false"


def test_better_candidate_is_marked_not_regressing(registry) -> None:
    model, x = registry

    version = _register(model, x, metrics={"accuracy": 0.99, "f1_macro": 0.99})

    mv = mlflow.MlflowClient().get_model_version(MODEL_NAME, version)
    assert mv.tags["regression"] == "false"


def test_approve_requires_an_actor(registry) -> None:
    model, x = registry
    version = _register(model, x)

    with pytest.raises(ApprovalError, match="actor"):
        approve(version, actor="", reason="looks fine")


def test_approve_sets_production_alias_and_records_who(registry) -> None:
    model, x = registry
    version = _register(model, x)

    approve(version, actor="analyst@lab", reason="reviewed charts, sensors replaced")

    mv = mlflow.MlflowClient().get_model_version(MODEL_NAME, version)
    assert mv.tags["approval_status"] == APPROVED
    assert mv.tags["approved_by"] == "analyst@lab"
    assert mv.tags["approval_reason"].startswith("reviewed charts")
    assert "approved_at" in mv.tags
    assert production_version() == version
    client = mlflow.MlflowClient()
    assert str(client.get_model_version_by_alias(MODEL_NAME, PRODUCTION_ALIAS).version) == version


def test_cannot_approve_twice(registry) -> None:
    model, x = registry
    version = _register(model, x)
    approve(version, actor="a@lab", reason="ok")

    with pytest.raises(ApprovalError, match="not pending"):
        approve(version, actor="b@lab", reason="again")


def test_reject_records_reason_and_leaves_production_untouched(registry) -> None:
    model, x = registry
    first = _register(model, x)
    approve(first, actor="a@lab", reason="baseline promotion")
    second = _register(model, x, metrics={"accuracy": 0.5, "f1_macro": 0.4})

    reject(second, actor="b@lab", reason="worse on acetaldehyde")

    mv = mlflow.MlflowClient().get_model_version(MODEL_NAME, second)
    assert mv.tags["approval_status"] == REJECTED
    assert mv.tags["rejected_by"] == "b@lab"
    assert mv.tags["rejection_reason"] == "worse on acetaldehyde"
    assert production_version() == first  # unchanged


def test_rejected_version_cannot_be_approved_later(registry) -> None:
    model, x = registry
    version = _register(model, x)
    reject(version, actor="a@lab", reason="no")

    with pytest.raises(ApprovalError, match="not pending"):
        approve(version, actor="a@lab", reason="changed my mind")


def test_rollback_restores_previous_approved_version(registry) -> None:
    model, x = registry
    v1 = _register(model, x)
    approve(v1, actor="a@lab", reason="first")
    v2 = _register(model, x)
    approve(v2, actor="a@lab", reason="second")
    assert production_version() == v2

    restored = rollback(actor="a@lab", reason="v2 misbehaving in service")

    assert restored == v1
    assert production_version() == v1
    mv2 = mlflow.MlflowClient().get_model_version(MODEL_NAME, v2)
    assert mv2.tags["approval_status"] == "rolled-back"
    assert mv2.tags["rolled_back_by"] == "a@lab"


def test_version_identifiers_are_always_strings(registry) -> None:
    """MLflow returns int on some paths; the CLI formats these into strings."""
    model, x = registry
    v1 = _register(model, x)
    approve(v1, actor="a@lab", reason="first")
    v2 = _register(model, x)
    approve(v2, actor="a@lab", reason="second")

    assert isinstance(production_version(), str)
    assert isinstance(rollback(actor="a@lab", reason="back"), str)
    assert isinstance(production_version(), str)
    assert all(isinstance(e["version"], str) for e in audit_trail())


def test_rollback_without_prior_approved_version_fails(registry) -> None:
    model, x = registry
    v1 = _register(model, x)
    approve(v1, actor="a@lab", reason="only one")

    with pytest.raises(ApprovalError, match="no earlier approved version"):
        rollback(actor="a@lab", reason="nothing to go back to")


def test_audit_trail_is_chronological_and_complete(registry) -> None:
    model, x = registry
    v1 = _register(model, x)
    approve(v1, actor="a@lab", reason="first")
    v2 = _register(model, x, metrics={"accuracy": 0.1, "f1_macro": 0.1})
    reject(v2, actor="b@lab", reason="regression")

    trail = audit_trail()

    assert [e["version"] for e in trail] == [v1, v2]
    assert trail[0]["approval_status"] == APPROVED
    assert trail[0]["approved_by"] == "a@lab"
    assert trail[1]["approval_status"] == REJECTED
    assert trail[1]["rejection_reason"] == "regression"
    assert all("trigger" in e for e in trail)


# --- audit log integration ---


def test_registry_actions_are_written_to_the_audit_log(registry, tmp_path, monkeypatch) -> None:
    from drift import registry as reg
    from drift.audit import read_events, verify_chain

    log = tmp_path / "audit.jsonl"
    monkeypatch.setattr(reg, "AUDIT_LOG_PATH", log)
    model, x = registry

    v1 = _register(model, x)
    approve(v1, actor="a@lab", reason="first")
    v2 = _register(model, x, metrics={"accuracy": 0.1, "f1_macro": 0.1})
    reject(v2, actor="b@lab", reason="regression")
    v3 = _register(model, x)
    approve(v3, actor="a@lab", reason="third")
    rollback(actor="c@lab", reason="bad in service")

    events = read_events(log)
    assert [e.action for e in events] == [
        "candidate_registered",
        "approved",
        "candidate_registered",
        "rejected",
        "candidate_registered",
        "approved",
        "rolled_back",
    ]
    assert [e.actor for e in events][1::2][:3] == ["a@lab", "b@lab", "a@lab"]
    assert events[1].details["version"] == v1
    assert events[3].details["reason"] == "regression"
    assert events[-1].details["restored_version"] == v1
    assert verify_chain(log) == 7
