"""Tests for the UCI Gas Sensor Array Drift loader."""

from pathlib import Path

import pandas as pd
import pytest

from drift.data import GAS_CLASSES, N_FEATURES, feature_columns, load_batch, parse_svmlight_line

SAMPLE_LINE = "3 1:15596.16 2:1.868 3:2.371 4:2.803 5:7.512 6:-2.739 7:-3.344 8:-4.847\n"


def test_parse_svmlight_line_returns_label_and_indexed_values() -> None:
    label, values = parse_svmlight_line(SAMPLE_LINE)

    assert label == 3
    assert values[1] == pytest.approx(15596.16)
    assert values[8] == pytest.approx(-4.847)
    assert len(values) == 8


def test_parse_svmlight_line_rejects_malformed_input() -> None:
    with pytest.raises(ValueError, match="malformed"):
        parse_svmlight_line("1 abc\n")


def test_feature_columns_has_128_names_in_sensor_order() -> None:
    cols = feature_columns()

    assert len(cols) == N_FEATURES == 128
    assert cols[0] == "s01_f1"
    assert cols[7] == "s01_f8"
    assert cols[8] == "s02_f1"
    assert cols[-1] == "s16_f8"


def test_load_batch_builds_dataframe_with_label_batch_and_features(tmp_path: Path) -> None:
    raw = tmp_path / "batch1.dat"
    raw.write_text(
        "1 " + " ".join(f"{i}:{float(i)}" for i in range(1, 129)) + "\n"
        "6 " + " ".join(f"{i}:{float(-i)}" for i in range(1, 129)) + "\n"
    )

    df = load_batch(1, raw_dir=tmp_path)

    assert list(df.columns[:2]) == ["batch", "label"]
    assert df.shape == (2, 2 + N_FEATURES)
    assert df["batch"].tolist() == [1, 1]
    assert df["label"].tolist() == [1, 6]
    assert df.loc[0, "s01_f1"] == pytest.approx(1.0)
    assert df.loc[1, "s16_f8"] == pytest.approx(-128.0)
    assert pd.api.types.is_integer_dtype(df["label"])


def test_load_batch_rejects_row_with_wrong_feature_count(tmp_path: Path) -> None:
    raw = tmp_path / "batch2.dat"
    raw.write_text("1 1:0.5 2:0.5\n")

    with pytest.raises(ValueError, match="expected 128 features"):
        load_batch(2, raw_dir=tmp_path)


def test_load_batch_rejects_unknown_label(tmp_path: Path) -> None:
    raw = tmp_path / "batch3.dat"
    raw.write_text("9 " + " ".join(f"{i}:0.0" for i in range(1, 129)) + "\n")

    with pytest.raises(ValueError, match="unknown gas class"):
        load_batch(3, raw_dir=tmp_path)


def test_load_batch_rejects_out_of_range_batch_number(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="batch must be 1-10"):
        load_batch(11, raw_dir=tmp_path)


def test_gas_classes_cover_labels_one_to_six() -> None:
    assert sorted(GAS_CLASSES) == [1, 2, 3, 4, 5, 6]
