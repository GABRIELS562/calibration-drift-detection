"""Train the baseline classifier on Batch 1 and register it in MLflow.

The model is deliberately simple (ADR-0002). What matters is that every run
records its parameters, metrics, and the SHA-256 of the data it was trained
on, so a prediction can be traced back to the exact bytes behind it.
"""

import os
from typing import Any, Final

import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split

from drift.data import RAW_DIR, feature_columns, load_batch
from drift.reference import (
    BASELINE_STATS_PATH,
    compute_reference_stats,
    sha256_of_file,
    write_reference_stats,
)

MODEL_NAME: Final = "calibration-drift-classifier"
EXPERIMENT_NAME: Final = "baseline"
REFERENCE_BATCH: Final = 1
DEFAULT_TRACKING_URI: Final = "sqlite:///mlflow.db"
DEFAULT_PARAMS: Final[dict[str, Any]] = {"n_estimators": 200, "max_depth": None, "seed": 42}
# MLflow serialises sklearn models with skops, which refuses to load types it has not been told
# to trust. Declaring the forest's tree type here keeps the safe format instead of pickle.
SKOPS_TRUSTED_TYPES: Final = ["sklearn.tree._tree.Tree"]
TEST_SIZE: Final = 0.25


def split_features_labels(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    return df[feature_columns()], df["label"]


def train_test_split_stratified(
    x: pd.DataFrame, y: pd.Series, *, test_size: float, seed: int
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    return train_test_split(x, y, test_size=test_size, random_state=seed, stratify=y)


def fit_baseline(
    x: pd.DataFrame,
    y: pd.Series,
    *,
    seed: int,
    n_estimators: int = 200,
    max_depth: int | None = None,
) -> RandomForestClassifier:
    """Random forest: no feature scaling needed despite f1 being ~1e5 and transients ~1e1."""
    model = RandomForestClassifier(
        n_estimators=n_estimators, max_depth=max_depth, random_state=seed, n_jobs=-1
    )
    return model.fit(x, y)


def evaluate(model: RandomForestClassifier, x: pd.DataFrame, y: pd.Series) -> dict[str, float]:
    pred = model.predict(x)
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "f1_macro": float(f1_score(y, pred, average="macro")),
    }


def log_run(
    model: RandomForestClassifier,
    *,
    metrics: dict[str, float],
    params: dict[str, Any],
    dataset_sha256: str,
    source: str,
    example: pd.DataFrame,
) -> tuple[str, str]:
    """Log one run and register the model. Returns ``(run_id, model_version)``."""
    if not metrics:
        raise ValueError("metrics must not be empty — an unevaluated model is not registrable")
    mlflow.set_experiment(EXPERIMENT_NAME)
    with mlflow.start_run() as run:
        mlflow.log_params({**params, "dataset_sha256": dataset_sha256, "source": source})
        mlflow.log_metrics(metrics)
        info = mlflow.sklearn.log_model(
            model,
            name="model",
            input_example=example,
            registered_model_name=MODEL_NAME,
            skops_trusted_types=SKOPS_TRUSTED_TYPES,
        )
    version = info.registered_model_version
    client = mlflow.MlflowClient()
    client.set_model_version_tag(MODEL_NAME, version, "dataset_sha256", dataset_sha256)
    client.set_model_version_tag(MODEL_NAME, version, "approval_status", "baseline")
    return run.info.run_id, version


def main() -> None:
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI))
    source_path = RAW_DIR / f"batch{REFERENCE_BATCH}.dat"
    dataset_sha256 = sha256_of_file(source_path)

    df = load_batch(REFERENCE_BATCH)
    x, y = split_features_labels(df)
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
    run_id, version = log_run(
        model,
        metrics=metrics,
        params={**DEFAULT_PARAMS, "test_size": TEST_SIZE},
        dataset_sha256=dataset_sha256,
        source=source_path.name,
        example=x_tr.head(3),
    )

    stats = compute_reference_stats(df, source=source_path.name, dataset_sha256=dataset_sha256)
    write_reference_stats(stats)

    print(f"run_id={run_id} model={MODEL_NAME} version={version}")
    print(f"metrics={metrics}")
    print(f"dataset_sha256={dataset_sha256}")
    print(f"reference stats -> {BASELINE_STATS_PATH}")


if __name__ == "__main__":
    main()
