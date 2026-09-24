"""Tests for baseline training and MLflow logging."""

from pathlib import Path

import mlflow
import pandas as pd
import pytest

from drift.train import (
    MODEL_NAME,
    evaluate,
    fit_baseline,
    log_run,
    split_features_labels,
    train_test_split_stratified,
)


def test_split_features_labels_drops_batch_and_label(synthetic_batch: pd.DataFrame) -> None:
    x, y = split_features_labels(synthetic_batch)

    assert "batch" not in x.columns and "label" not in x.columns
    assert x.shape == (len(synthetic_batch), 128)
    assert y.tolist() == synthetic_batch["label"].tolist()


def test_stratified_split_preserves_class_balance(synthetic_batch: pd.DataFrame) -> None:
    x, y = split_features_labels(synthetic_batch)

    x_tr, x_te, y_tr, y_te = train_test_split_stratified(x, y, test_size=0.25, seed=1)

    assert len(x_te) == 30
    assert y_te.value_counts().tolist() == [5] * 6
    assert len(x_tr) + len(x_te) == len(x)


def test_fit_and_evaluate_learns_separable_classes(synthetic_batch: pd.DataFrame) -> None:
    x, y = split_features_labels(synthetic_batch)
    x_tr, x_te, y_tr, y_te = train_test_split_stratified(x, y, test_size=0.25, seed=1)

    model = fit_baseline(x_tr, y_tr, seed=1)
    metrics = evaluate(model, x_te, y_te)

    assert set(metrics) == {"accuracy", "f1_macro"}
    assert metrics["accuracy"] > 0.9
    assert metrics["f1_macro"] > 0.9


def test_log_run_registers_model_with_dataset_hash(
    synthetic_batch: pd.DataFrame, tmp_path: Path
) -> None:
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'mlflow.db'}")
    x, y = split_features_labels(synthetic_batch)
    model = fit_baseline(x, y, seed=1)

    run_id, version = log_run(
        model,
        metrics={"accuracy": 1.0, "f1_macro": 1.0},
        params={"n_estimators": 10, "seed": 1},
        dataset_sha256="cafe",
        source="batch1.dat",
        example=x.head(2),
    )

    run = mlflow.get_run(run_id)
    assert run.data.params["dataset_sha256"] == "cafe"
    assert run.data.params["source"] == "batch1.dat"
    assert run.data.metrics["accuracy"] == 1.0
    mv = mlflow.MlflowClient().get_model_version(MODEL_NAME, version)
    assert mv.run_id == run_id
    assert mv.tags["dataset_sha256"] == "cafe"
    assert mv.tags["approval_status"] == "pending-approval"  # even v1 needs a human


def test_log_run_writes_a_baseline_registration_to_the_audit_log(
    synthetic_batch: pd.DataFrame, tmp_path: Path, isolate_audit_log
) -> None:
    from drift.audit import read_events, verify_chain

    log = isolate_audit_log
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'mlflow.db'}")
    x, y = split_features_labels(synthetic_batch)
    model = fit_baseline(x, y, seed=1)

    _, version = log_run(
        model,
        metrics={"accuracy": 1.0, "f1_macro": 1.0},
        params={"seed": 1},
        dataset_sha256="cafe",
        source="batch1.dat",
        example=x.head(2),
    )

    events = read_events(log)
    assert [e.action for e in events] == ["baseline_registered"]
    assert events[0].details["version"] == version
    assert events[0].details["dataset_sha256"] == "cafe"
    assert verify_chain(log) == 1


def test_log_run_rejects_empty_metrics(synthetic_batch: pd.DataFrame, tmp_path: Path) -> None:
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'mlflow.db'}")
    x, y = split_features_labels(synthetic_batch)
    model = fit_baseline(x, y, seed=1)

    with pytest.raises(ValueError, match="metrics"):
        log_run(model, metrics={}, params={}, dataset_sha256="c", source="s", example=x.head(1))
