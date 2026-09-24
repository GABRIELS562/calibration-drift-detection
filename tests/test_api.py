"""Tests for the serving API."""

import mlflow
import pytest
from fastapi.testclient import TestClient

from drift.api import app, get_state
from drift.data import feature_columns
from drift.metrics import COUNTERS
from drift.registry import approve
from drift.train import fit_baseline, log_run, split_features_labels


@pytest.fixture
def client(synthetic_batch, tmp_path, monkeypatch):
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
    approve(version, actor="test@lab", reason="fixture")
    get_state.cache_clear()
    COUNTERS.reset()
    with TestClient(app) as c:
        yield c, x


def test_health_is_unauthenticated_and_cheap(client) -> None:
    c, _ = client

    response = c.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_reports_the_served_model_version(client) -> None:
    c, _ = client

    body = c.get("/ready").json()

    assert body["ready"] is True
    assert body["model_version"] == "1"
    assert body["dataset_sha256"] == "cafe"


def test_predict_returns_a_class_and_the_serving_version(client) -> None:
    c, x = client
    row = {col: float(x.iloc[0][col]) for col in feature_columns()}

    body = c.post("/predict", json={"features": row}).json()

    assert body["prediction"] in range(1, 7)
    assert body["gas"]
    assert body["model_version"] == "1"
    assert body["dataset_sha256"] == "cafe"


def test_predict_rejects_a_missing_feature(client) -> None:
    c, x = client
    row = {col: float(x.iloc[0][col]) for col in feature_columns()}
    row.pop("s01_f1")

    response = c.post("/predict", json={"features": row})

    assert response.status_code == 422
    assert "s01_f1" in response.text


def test_predict_rejects_an_unknown_feature(client) -> None:
    c, x = client
    row = {col: float(x.iloc[0][col]) for col in feature_columns()}
    row["not_a_sensor"] = 1.0

    response = c.post("/predict", json={"features": row})

    assert response.status_code == 422
    assert "not_a_sensor" in response.text


def test_predict_rejects_a_non_numeric_value(client) -> None:
    c, x = client
    row = {col: float(x.iloc[0][col]) for col in feature_columns()}
    row["s01_f1"] = "warm"

    assert c.post("/predict", json={"features": row}).status_code == 422


def test_drift_status_exposes_the_latest_verdict(client) -> None:
    c, _ = client

    body = c.get("/drift-status").json()

    assert "rejected_sensors" in body and "warned_sensors" in body
    assert "evaluated_at" in body


def test_metrics_are_prometheus_text(client) -> None:
    c, x = client
    row = {col: float(x.iloc[0][col]) for col in feature_columns()}
    c.post("/predict", json={"features": row})

    response = c.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "# TYPE drift_predictions_total counter" in response.text
    assert "drift_predictions_total 1" in response.text


def test_metrics_include_model_and_drift_gauges(client) -> None:
    c, _ = client

    text = c.get("/metrics").text

    assert "drift_model_info" in text
    assert "drift_sensors_rejected" in text
    assert "drift_candidates_pending" in text


def test_predictions_are_counted_per_request(client) -> None:
    c, x = client
    row = {col: float(x.iloc[0][col]) for col in feature_columns()}

    for _ in range(3):
        c.post("/predict", json={"features": row})

    assert COUNTERS.get("drift_predictions_total") == 3


def test_predict_fails_cleanly_when_nothing_is_approved(synthetic_batch, tmp_path) -> None:
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'empty.db'}")
    get_state.cache_clear()
    x, _ = split_features_labels(synthetic_batch)
    row = {col: float(x.iloc[0][col]) for col in feature_columns()}

    with TestClient(app) as c:
        assert c.get("/ready").json()["ready"] is False
        response = c.post("/predict", json={"features": row})

    assert response.status_code == 503
    assert "no approved model" in response.text.lower()
    get_state.cache_clear()


# --- degradation when the registry is unreachable (found by a container smoke test) ---


@pytest.fixture
def unreachable_registry(monkeypatch, tmp_path):
    """No registry at all: a path that cannot be opened."""
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'nonexistent-dir' / 'x.db'}")
    get_state.cache_clear()
    COUNTERS.reset()
    with TestClient(app) as c:
        yield c
    get_state.cache_clear()


def test_ready_reports_not_ready_instead_of_erroring(unreachable_registry) -> None:
    response = unreachable_registry.get("/ready")

    assert response.status_code == 200
    assert response.json()["ready"] is False


def test_health_still_succeeds_without_a_registry(unreachable_registry) -> None:
    assert unreachable_registry.get("/health").status_code == 200


def test_metrics_still_render_without_a_registry(unreachable_registry) -> None:
    response = unreachable_registry.get("/metrics")

    assert response.status_code == 200
    assert "drift_model_ready 0" in response.text
    assert "drift_candidates_pending 0" in response.text


def test_drift_status_still_responds_without_a_registry(unreachable_registry) -> None:
    assert unreachable_registry.get("/drift-status").status_code == 200


def test_predict_returns_503_not_500_without_a_registry(unreachable_registry) -> None:
    row = {c: 0.0 for c in feature_columns()}

    response = unreachable_registry.post("/predict", json={"features": row})

    assert response.status_code == 503
