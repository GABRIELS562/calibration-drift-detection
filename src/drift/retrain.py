"""Drift-triggered retraining: produce a candidate, never a replacement.

A rejected sensor (ADR-0003) triggers retraining. The candidate is trained
on the reference batch plus every production batch seen so far, evaluated
against the incumbent on the same held-out data, and registered as
pending-approval. Nothing here promotes anything (ADR-0004).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import mlflow
import pandas as pd

from drift.data import GAS_CLASSES
from drift.registry import PRODUCTION_ALIAS, register_candidate
from drift.train import (
    DEFAULT_PARAMS,
    MODEL_NAME,
    TEST_SIZE,
    evaluate,
    fit_baseline,
    split_features_labels,
    train_test_split_stratified,
)
from drift.westgard import Verdict, WestgardResult

_UNTRAINED_INCUMBENT: Final[dict[str, float]] = {}


@dataclass(frozen=True)
class TriggerDecision:
    triggered: bool
    batch: int
    rejected_sensors: tuple[str, ...]
    reason: str


def should_retrain(result: WestgardResult) -> TriggerDecision:
    """Any rejected sensor triggers a candidate; warnings alone do not."""
    rejected = result.rejected_sensors
    if not rejected:
        warned = result.warned_sensors
        reason = f"batch {result.current_batch}: no sensor rejected" + (
            f"; {len(warned)} under warn ({', '.join(warned)})" if warned else "; all in control"
        )
        return TriggerDecision(False, result.current_batch, (), reason)

    details = []
    for sensor in result.sensors:
        if sensor.status is not Verdict.REJECT:
            continue
        worst = max(sensor.triggers, key=lambda c: abs(c.z or 0.0))
        rules = "+".join(sorted(r.value for r in worst.rules))
        details.append(f"{sensor.sensor} ({GAS_CLASSES[worst.gas]} z={worst.z:+.1f} {rules})")
    reason = f"batch {result.current_batch}: {len(rejected)} sensor(s) rejected — " + ", ".join(
        details
    )
    return TriggerDecision(True, result.current_batch, rejected, reason)


def _incumbent_metrics(x: pd.DataFrame, y: pd.Series) -> dict[str, float]:
    """Score the model currently in production on the candidate's held-out data."""
    try:
        model = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}@{PRODUCTION_ALIAS}")
    except Exception:
        return _UNTRAINED_INCUMBENT
    return evaluate(model, x, y)


def train_candidate_for_batch(
    decision: TriggerDecision,
    *,
    reference: pd.DataFrame,
    history: Sequence[pd.DataFrame],
    current: pd.DataFrame,
    dataset_sha256: str,
) -> str:
    """Train on reference + everything seen so far; register as pending."""
    if not decision.triggered:
        raise ValueError("not triggered — a candidate is only produced for a rejected sensor")

    training = pd.concat([reference, *history, current], ignore_index=True)
    x, y = split_features_labels(training)
    x_tr, x_te, y_tr, y_te = train_test_split_stratified(
        x, y, test_size=TEST_SIZE, seed=DEFAULT_PARAMS["seed"]
    )
    model = fit_baseline(
        x_tr,
        y_tr,
        seed=DEFAULT_PARAMS["seed"],
        n_estimators=DEFAULT_PARAMS["n_estimators"],
        max_depth=DEFAULT_PARAMS["max_depth"],
    )
    metrics = evaluate(model, x_te, y_te)
    incumbent = _incumbent_metrics(x_te, y_te)
    batches = sorted({int(b) for b in training["batch"].unique()})
    return register_candidate(
        model,
        metrics=metrics,
        incumbent_metrics=incumbent,
        params={**DEFAULT_PARAMS, "test_size": TEST_SIZE, "training_batches": str(batches)},
        dataset_sha256=dataset_sha256,
        trigger=decision.reason,
        example=x_tr.head(3),
    )
