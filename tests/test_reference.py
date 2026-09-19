"""Tests for reference-distribution statistics."""

import json
from pathlib import Path

import pandas as pd
import pytest

from drift.data import N_FEATURES
from drift.reference import (
    N_BINS,
    compute_reference_stats,
    sha256_of_file,
    write_reference_stats,
)


def test_sha256_of_file_matches_known_digest(tmp_path: Path) -> None:
    f = tmp_path / "x.dat"
    f.write_bytes(b"abc")

    assert sha256_of_file(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_compute_reference_stats_has_one_entry_per_feature(synthetic_batch: pd.DataFrame) -> None:
    stats = compute_reference_stats(synthetic_batch, source="batch1.dat", dataset_sha256="deadbeef")

    assert stats["source"] == "batch1.dat"
    assert stats["dataset_sha256"] == "deadbeef"
    assert stats["n_rows"] == len(synthetic_batch)
    assert len(stats["features"]) == N_FEATURES
    assert stats["label_counts"] == {str(k): 20 for k in range(1, 7)}


def test_feature_entry_contains_moments_and_bins(synthetic_batch: pd.DataFrame) -> None:
    stats = compute_reference_stats(synthetic_batch, source="s", dataset_sha256="d")
    entry = stats["features"]["s01_f1"]
    col = synthetic_batch["s01_f1"]

    assert entry["mean"] == pytest.approx(col.mean())
    assert entry["std"] == pytest.approx(col.std())
    assert entry["min"] == pytest.approx(col.min())
    assert entry["max"] == pytest.approx(col.max())
    assert len(entry["bin_edges"]) == N_BINS + 1
    assert len(entry["bin_counts"]) == N_BINS
    assert sum(entry["bin_counts"]) == len(col)


def test_compute_reference_stats_rejects_multiple_batches(synthetic_batch: pd.DataFrame) -> None:
    mixed = pd.concat([synthetic_batch, synthetic_batch.assign(batch=2)])

    with pytest.raises(ValueError, match="single batch"):
        compute_reference_stats(mixed, source="s", dataset_sha256="d")


def test_write_reference_stats_round_trips_as_json(
    synthetic_batch: pd.DataFrame, tmp_path: Path
) -> None:
    stats = compute_reference_stats(synthetic_batch, source="s", dataset_sha256="d")
    out = tmp_path / "baseline_stats.json"

    write_reference_stats(stats, out)

    assert json.loads(out.read_text()) == stats
