"""Tests for drift detection against the Batch 1 reference."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from drift.detect import (
    ColumnDrift,
    DriftConfig,
    DriftResult,
    parse_snapshot,
    run_drift_check,
    save_reports,
)

CONFIG = DriftConfig()


def _test_entry(column: str, method: str, threshold: float, status: str) -> dict:
    return {
        "id": "drift",
        "name": f"Value Drift for column {column}",
        "metric_config": {
            "params": {
                "type": "evidently:metric_v2:ValueDrift",
                "column": column,
                "method": method,
                "threshold": threshold,
            }
        },
        "status": status,
    }


def _metric_entry(column: str, method: str, threshold: float, value: float) -> dict:
    return {
        "metric_name": f"ValueDrift(column={column},method={method},threshold={threshold})",
        "config": {
            "type": "evidently:metric_v2:ValueDrift",
            "column": column,
            "method": method,
            "threshold": threshold,
        },
        "value": value,
    }


@pytest.fixture
def snapshot_dict() -> dict:
    return {
        "metrics": [
            _metric_entry("s01_f1", "psi", 0.25, 0.96),
            _metric_entry("s01_f2", "psi", 0.25, 0.10),
            _metric_entry("label", "chisquare", 0.05, 1e-9),
        ],
        "tests": [
            {"id": "lt", "name": "Share of Drifted Columns", "status": "FAIL"},
            _test_entry("s01_f1", "psi", 0.25, "FAIL"),
            _test_entry("s01_f2", "psi", 0.25, "SUCCESS"),
            _test_entry("label", "chisquare", 0.05, "FAIL"),
        ],
    }


def test_default_config_uses_psi_for_features_and_chisquare_for_label() -> None:
    assert CONFIG.num_method == "psi"
    assert CONFIG.num_threshold == 0.25
    assert CONFIG.cat_method == "chisquare"
    assert CONFIG.cat_threshold == 0.05


def test_config_rejects_unknown_method() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        DriftConfig(num_method="magic")


def test_parse_snapshot_separates_features_from_label(snapshot_dict: dict) -> None:
    result = parse_snapshot(
        snapshot_dict,
        config=CONFIG,
        reference_batch=1,
        current_batch=2,
        n_reference=445,
        n_current=1244,
    )

    assert result.reference_batch == 1 and result.current_batch == 2
    assert result.n_reference == 445 and result.n_current == 1244
    assert [c.column for c in result.features] == ["s01_f1", "s01_f2"]
    assert result.features[0] == ColumnDrift("s01_f1", "psi", 0.96, 0.25, True)
    assert result.features[1].drifted is False
    assert result.label == ColumnDrift("label", "chisquare", 1e-9, 0.05, True)


def test_result_counts_and_share(snapshot_dict: dict) -> None:
    result = parse_snapshot(
        snapshot_dict, config=CONFIG, reference_batch=1, current_batch=2, n_reference=1, n_current=1
    )

    assert result.n_drifted == 1
    assert result.share_drifted == pytest.approx(0.5)
    assert result.drifted_features == ("s01_f1",)
    assert result.breached is True  # share 0.5 >= drift_share 0.5


def test_parse_snapshot_fails_loudly_when_test_has_no_metric(snapshot_dict: dict) -> None:
    snapshot_dict["metrics"] = snapshot_dict["metrics"][:1]

    with pytest.raises(ValueError, match="no metric value for column"):
        parse_snapshot(
            snapshot_dict,
            config=CONFIG,
            reference_batch=1,
            current_batch=2,
            n_reference=1,
            n_current=1,
        )


def test_parse_snapshot_fails_when_label_missing(snapshot_dict: dict) -> None:
    snapshot_dict["tests"] = [t for t in snapshot_dict["tests"] if "label" not in t["name"]]

    with pytest.raises(ValueError, match="label"):
        parse_snapshot(
            snapshot_dict,
            config=CONFIG,
            reference_batch=1,
            current_batch=2,
            n_reference=1,
            n_current=1,
        )


def test_result_is_immutable(snapshot_dict: dict) -> None:
    result = parse_snapshot(
        snapshot_dict, config=CONFIG, reference_batch=1, current_batch=2, n_reference=1, n_current=1
    )

    with pytest.raises(AttributeError):
        result.current_batch = 9  # type: ignore[misc]


def test_run_drift_check_detects_shift_and_ignores_identical(synthetic_batch: pd.DataFrame) -> None:
    rng = np.random.default_rng(1)
    shifted = synthetic_batch.assign(batch=2)
    shifted["s01_f1"] = shifted["s01_f1"] + 100.0  # gross shift on one feature
    shifted["s01_f2"] = shifted["s01_f2"] + rng.normal(0, 0.01, len(shifted))  # noise only

    result, snapshot = run_drift_check(synthetic_batch, shifted, config=CONFIG)

    by_col = {c.column: c for c in result.features}
    assert by_col["s01_f1"].drifted is True
    assert by_col["s01_f2"].drifted is False
    assert result.label.drifted is False  # same label mix
    assert len(result.features) == 128
    assert snapshot is not None


def test_run_drift_check_rejects_same_batch(synthetic_batch: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="different batches"):
        run_drift_check(synthetic_batch, synthetic_batch, config=CONFIG)


def test_save_reports_writes_html_and_json(synthetic_batch: pd.DataFrame, tmp_path: Path) -> None:
    shifted = synthetic_batch.assign(batch=3)
    result, snapshot = run_drift_check(synthetic_batch, shifted, config=CONFIG)

    html, js = save_reports(result, snapshot, out_dir=tmp_path)

    assert html.name == "batch3.html" and js.name == "batch3.json"
    assert html.stat().st_size > 1000
    loaded = json.loads(js.read_text())
    assert loaded["current_batch"] == 3
    assert loaded["n_drifted"] == 0
    assert isinstance(loaded["features"], list) and len(loaded["features"]) == 128


def test_drift_result_to_dict_is_json_serialisable(snapshot_dict: dict) -> None:
    result = parse_snapshot(
        snapshot_dict, config=CONFIG, reference_batch=1, current_batch=2, n_reference=1, n_current=1
    )
    d = result.to_dict()
    json.dumps(d)
    assert d["config"]["num_method"] == "psi"
    assert isinstance(result, DriftResult)
