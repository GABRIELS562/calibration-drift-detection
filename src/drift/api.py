"""Serving API for the approved model.

Only the version behind the ``production`` alias is served, and every
prediction returns that version and the hash of the data it was trained on
— the first link of the traceability chain (``docs/traceability.md``).

Endpoints:
    GET  /health        liveness: the process is up
    GET  /ready         readiness: an approved model is loaded
    POST /predict       classify one sample
    GET  /drift-status  the most recent control-chart verdict
    GET  /metrics       Prometheus text
"""

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import mlflow
import mlflow.sklearn
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from drift.constants import MODEL_NAME, PENDING, PRODUCTION_ALIAS
from drift.data import GAS_CLASSES, feature_columns
from drift.detect import ARTIFACTS_DIR
from drift.metrics import COUNTERS

PREDICTIONS_TOTAL: Final = "drift_predictions_total"
PREDICTION_ERRORS_TOTAL: Final = "drift_prediction_errors_total"
_FEATURES: Final = feature_columns()


class PredictRequest(BaseModel):
    """All 128 features are required; unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")

    features: dict[str, float] = Field(description="s01_f1 … s16_f8")


class PredictResponse(BaseModel):
    prediction: int
    gas: str
    model_version: str
    dataset_sha256: str


@dataclass(frozen=True)
class ServingState:
    model: Any | None
    version: str | None
    dataset_sha256: str | None

    @property
    def ready(self) -> bool:
        return self.model is not None


NOT_READY: Final = ServingState(None, None, None)


@lru_cache(maxsize=1)
def get_state() -> ServingState:
    """Load the approved model once. Cleared by ``get_state.cache_clear()``.

    Every failure degrades to "not ready" rather than raising: an
    unreachable registry must make the readiness probe answer ``false``,
    not return 500. Constructing the client is inside the guard because it
    opens the backend connection and can fail on its own.
    """
    try:
        client = mlflow.MlflowClient()
        version = client.get_model_version_by_alias(MODEL_NAME, PRODUCTION_ALIAS)
        model = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}@{PRODUCTION_ALIAS}")
    except Exception:
        return NOT_READY
    return ServingState(model, str(version.version), version.tags.get("dataset_sha256", "unknown"))


def _latest_verdict() -> dict[str, Any]:
    """The newest Westgard result written by the pipeline, if there is one."""
    try:
        found = ARTIFACTS_DIR.glob("*/westgard/batch*.json")
        candidates = sorted(found, key=lambda p: p.stat().st_mtime)
        if not candidates:
            return {}
        return json.loads(Path(candidates[-1]).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _pending_candidates() -> int:
    try:
        versions = mlflow.MlflowClient().search_model_versions(f"name='{MODEL_NAME}'")
    except Exception:
        return 0
    return sum(1 for v in versions if v.tags.get("approval_status") == PENDING)


app = FastAPI(title="Calibration drift detection", version="1.0.0")


@app.on_event("startup")
def _configure_tracking() -> None:
    """Point MLflow at the configured registry. Deployment sets the env var."""
    uri = os.environ.get("MLFLOW_TRACKING_URI")
    if uri:
        mlflow.set_tracking_uri(uri)
        get_state.cache_clear()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, Any]:
    state = get_state()
    return {
        "ready": state.ready,
        "model_version": state.version,
        "dataset_sha256": state.dataset_sha256,
    }


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest) -> PredictResponse:
    state = get_state()
    if not state.ready:
        COUNTERS.increment(PREDICTION_ERRORS_TOTAL)
        raise HTTPException(status_code=503, detail="no approved model in production")

    missing = [c for c in _FEATURES if c not in request.features]
    unknown = [c for c in request.features if c not in _FEATURES]
    if missing or unknown:
        COUNTERS.increment(PREDICTION_ERRORS_TOTAL)
        detail = []
        if missing:
            detail.append(f"missing features: {missing[:5]}")
        if unknown:
            detail.append(f"unknown features: {unknown[:5]}")
        raise HTTPException(status_code=422, detail="; ".join(detail))

    frame = pd.DataFrame([[request.features[c] for c in _FEATURES]], columns=_FEATURES)
    label = int(state.model.predict(frame)[0])
    COUNTERS.increment(PREDICTIONS_TOTAL)
    return PredictResponse(
        prediction=label,
        gas=GAS_CLASSES[label],
        model_version=state.version or "unknown",
        dataset_sha256=state.dataset_sha256 or "unknown",
    )


@app.get("/drift-status")
def drift_status() -> dict[str, Any]:
    verdict = _latest_verdict()
    return {
        "batch": verdict.get("current_batch"),
        "reference_batch": verdict.get("reference_batch"),
        "rejected_sensors": verdict.get("rejected_sensors", []),
        "warned_sensors": verdict.get("warned", []),
        "evaluated_at": verdict.get("evaluated_at"),
        "candidates_pending_approval": _pending_candidates(),
    }


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    state = get_state()
    verdict = _latest_verdict()
    gauges = [
        "# TYPE drift_model_info gauge",
        f'drift_model_info{{version="{state.version or "none"}",'
        f'dataset_sha256="{state.dataset_sha256 or "none"}"}} 1',
        "# TYPE drift_model_ready gauge",
        f"drift_model_ready {int(state.ready)}",
        "# TYPE drift_sensors_rejected gauge",
        f"drift_sensors_rejected {len(verdict.get('rejected_sensors', []))}",
        "# TYPE drift_sensors_warned gauge",
        f"drift_sensors_warned {len(verdict.get('warned', []))}",
        "# TYPE drift_candidates_pending gauge",
        f"drift_candidates_pending {_pending_candidates()}",
    ]
    counters = COUNTERS.render_prometheus()
    if PREDICTIONS_TOTAL not in COUNTERS.values:
        counters = f"# TYPE {PREDICTIONS_TOTAL} counter\n{PREDICTIONS_TOTAL} 0\n" + counters
    return "\n".join(gauges) + "\n" + counters
