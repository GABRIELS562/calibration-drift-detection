"""Reference-distribution statistics.

The reference is computed from Batch 1 *only* and committed to
``data/reference/baseline_stats.json``. It is part of the validated system
state: a change to it is a change to the system and goes through review.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from drift.data import feature_columns

REFERENCE_DIR: Final = Path(__file__).resolve().parents[2] / "data" / "reference"
BASELINE_STATS_PATH: Final = REFERENCE_DIR / "baseline_stats.json"
N_BINS: Final = 10
_HASH_CHUNK: Final = 1 << 20


def sha256_of_file(path: Path) -> str:
    """Hex SHA-256 of a file, streamed so large batches don't load into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _feature_entry(col: pd.Series) -> dict[str, Any]:
    counts, edges = np.histogram(col, bins=N_BINS)
    return {
        "mean": float(col.mean()),
        "std": float(col.std()),
        "min": float(col.min()),
        "max": float(col.max()),
        "bin_edges": [float(e) for e in edges],
        "bin_counts": [int(c) for c in counts],
    }


def compute_reference_stats(
    df: pd.DataFrame, *, source: str, dataset_sha256: str
) -> dict[str, Any]:
    """Per-feature moments and histogram bins plus provenance for one batch."""
    batches = df["batch"].unique()
    if len(batches) != 1:
        raise ValueError(f"reference must come from a single batch, got {sorted(batches)}")
    label_counts = df["label"].value_counts().sort_index()
    return {
        "source": source,
        "dataset_sha256": dataset_sha256,
        "batch": int(batches[0]),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_rows": int(len(df)),
        "n_bins": N_BINS,
        "label_counts": {str(k): int(v) for k, v in label_counts.items()},
        "features": {name: _feature_entry(df[name]) for name in feature_columns()},
    }


def write_reference_stats(stats: dict[str, Any], path: Path = BASELINE_STATS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=2) + "\n")


def read_reference_stats(path: Path = BASELINE_STATS_PATH) -> dict[str, Any]:
    stats = json.loads(path.read_text())
    missing = {"source", "dataset_sha256", "features"} - stats.keys()
    if missing:
        raise ValueError(f"{path} is not a reference stats file: missing {sorted(missing)}")
    return stats
