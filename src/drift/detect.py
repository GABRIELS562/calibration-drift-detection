"""Drift detection: a production batch against the Batch 1 reference.

Every feature is continuous (README, "The data"), so numerical features use
PSI by default and the categorical label uses chi-square. KS is available
but, with 445 reference rows against batches of 1,000+, it flags every
feature on every batch — see ADR-0003.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
from evidently import DataDefinition, Dataset, Report
from evidently.presets import DataDriftPreset

from drift.data import feature_columns

ARTIFACTS_DIR: Final = Path(__file__).resolve().parents[2] / "artifacts" / "drift"
LABEL_COLUMN: Final = "label"
NUMERICAL_METHODS: Final = frozenset({"psi", "ks", "wasserstein", "jensenshannon", "hellinger"})
CATEGORICAL_METHODS: Final = frozenset({"chisquare", "psi", "jensenshannon", "TVD"})
_VALUE_DRIFT_TYPE: Final = "evidently:metric_v2:ValueDrift"


@dataclass(frozen=True)
class DriftConfig:
    """Thresholds are the subject of ADR-0003; change them there first."""

    num_method: str = "psi"
    num_threshold: float = 0.25
    cat_method: str = "chisquare"
    cat_threshold: float = 0.05
    drift_share: float = 0.5

    def __post_init__(self) -> None:
        if self.num_method not in NUMERICAL_METHODS:
            raise ValueError(f"unsupported num_method {self.num_method!r}")
        if self.cat_method not in CATEGORICAL_METHODS:
            raise ValueError(f"unsupported cat_method {self.cat_method!r}")


DEFAULT_CONFIG: Final = DriftConfig()


@dataclass(frozen=True)
class ColumnDrift:
    column: str
    method: str
    score: float
    threshold: float
    drifted: bool


@dataclass(frozen=True)
class DriftResult:
    reference_batch: int
    current_batch: int
    n_reference: int
    n_current: int
    config: DriftConfig
    features: tuple[ColumnDrift, ...]
    label: ColumnDrift
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )

    @property
    def drifted_features(self) -> tuple[str, ...]:
        return tuple(c.column for c in self.features if c.drifted)

    @property
    def n_drifted(self) -> int:
        return len(self.drifted_features)

    @property
    def share_drifted(self) -> float:
        return self.n_drifted / len(self.features) if self.features else 0.0

    @property
    def breached(self) -> bool:
        """Feature drift breaches when the drifted share reaches ``config.drift_share``."""
        return self.share_drifted >= self.config.drift_share

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "n_drifted": self.n_drifted,
            "share_drifted": self.share_drifted,
            "breached": self.breached,
            "drifted_features": list(self.drifted_features),
        }


def _data_definition() -> DataDefinition:
    return DataDefinition(numerical_columns=feature_columns(), categorical_columns=[LABEL_COLUMN])


def _to_dataset(df: pd.DataFrame) -> Dataset:
    return Dataset.from_pandas(df.drop(columns="batch"), data_definition=_data_definition())


def build_report(config: DriftConfig) -> Report:
    preset = DataDriftPreset(
        num_method=config.num_method,
        num_threshold=config.num_threshold,
        cat_method=config.cat_method,
        cat_threshold=config.cat_threshold,
        drift_share=config.drift_share,
    )
    return Report([preset], include_tests=True)


def _value_drift_scores(snapshot: dict[str, Any]) -> dict[str, float]:
    return {
        m["config"]["column"]: float(m["value"])
        for m in snapshot["metrics"]
        if m.get("config", {}).get("type") == _VALUE_DRIFT_TYPE
    }


def _column_drifts(snapshot: dict[str, Any]) -> list[ColumnDrift]:
    scores = _value_drift_scores(snapshot)
    drifts = []
    for test in snapshot["tests"]:
        params = test.get("metric_config", {}).get("params", {})
        if params.get("type") != _VALUE_DRIFT_TYPE:
            continue
        column = params["column"]
        if column not in scores:
            raise ValueError(f"snapshot has no metric value for column {column!r}")
        status = getattr(test["status"], "value", test["status"])
        drifts.append(
            ColumnDrift(
                column, params["method"], scores[column], params["threshold"], status == "FAIL"
            )
        )
    return drifts


def parse_snapshot(
    snapshot: dict[str, Any],
    *,
    config: DriftConfig,
    reference_batch: int,
    current_batch: int,
    n_reference: int,
    n_current: int,
) -> DriftResult:
    """Turn Evidently's snapshot dict into an immutable, serialisable result."""
    drifts = _column_drifts(snapshot)
    labels = [d for d in drifts if d.column == LABEL_COLUMN]
    if len(labels) != 1:
        raise ValueError(
            f"expected exactly one drift result for {LABEL_COLUMN!r}, got {len(labels)}"
        )
    features = tuple(d for d in drifts if d.column != LABEL_COLUMN)
    return DriftResult(
        reference_batch=reference_batch,
        current_batch=current_batch,
        n_reference=n_reference,
        n_current=n_current,
        config=config,
        features=features,
        label=labels[0],
    )


def run_drift_check(
    reference: pd.DataFrame, current: pd.DataFrame, *, config: DriftConfig = DEFAULT_CONFIG
) -> tuple[DriftResult, Any]:
    """Run Evidently and return ``(result, snapshot)``; the snapshot renders the HTML report."""
    ref_batch, cur_batch = int(reference["batch"].iloc[0]), int(current["batch"].iloc[0])
    if ref_batch == cur_batch:
        raise ValueError("reference and current must be different batches")
    snapshot = build_report(config).run(
        current_data=_to_dataset(current), reference_data=_to_dataset(reference)
    )
    result = parse_snapshot(
        snapshot.dict(),
        config=config,
        reference_batch=ref_batch,
        current_batch=cur_batch,
        n_reference=len(reference),
        n_current=len(current),
    )
    return result, snapshot


def save_reports(result: DriftResult, snapshot: Any, *, out_dir: Path) -> tuple[Path, Path]:
    """Write ``batchN.html`` (Evidently report) and ``batchN.json`` (our result)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    html = out_dir / f"batch{result.current_batch}.html"
    js = out_dir / f"batch{result.current_batch}.json"
    snapshot.save_html(str(html))
    js.write_text(json.dumps(result.to_dict(), indent=2) + "\n")
    return html, js
