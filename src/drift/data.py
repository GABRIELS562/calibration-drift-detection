"""Loader for the UCI Gas Sensor Array Drift dataset.

The raw files are in svmlight format: one sample per line, a gas-class label
followed by ``index:value`` pairs for 128 features. The 128 features are 16
metal-oxide sensors x 8 features per sensor, in sensor-major order.
"""

from pathlib import Path
from typing import Final

import pandas as pd

RAW_DIR: Final = Path(__file__).resolve().parents[2] / "data" / "raw"

N_SENSORS: Final = 16
FEATURES_PER_SENSOR: Final = 8
N_FEATURES: Final = N_SENSORS * FEATURES_PER_SENSOR
N_BATCHES: Final = 10

GAS_CLASSES: Final[dict[int, str]] = {
    1: "ethanol",
    2: "ethylene",
    3: "ammonia",
    4: "acetaldehyde",
    5: "acetone",
    6: "toluene",
}


def feature_columns() -> list[str]:
    """Column names ``s01_f1`` ... ``s16_f8`` matching the raw feature order."""
    return [
        f"s{sensor:02d}_f{feature}"
        for sensor in range(1, N_SENSORS + 1)
        for feature in range(1, FEATURES_PER_SENSOR + 1)
    ]


def parse_svmlight_line(line: str) -> tuple[int, dict[int, float]]:
    """Parse one svmlight line into ``(label, {index: value})``."""
    tokens = line.split()
    if not tokens:
        raise ValueError("malformed svmlight line: empty")
    try:
        label = int(tokens[0])
        values = {int(idx): float(val) for idx, val in (t.split(":", 1) for t in tokens[1:])}
    except ValueError as exc:
        raise ValueError(f"malformed svmlight line: {line[:60]!r}") from exc
    return label, values


def _row_from_line(line: str, batch: int, line_no: int) -> list[float]:
    label, values = parse_svmlight_line(line)
    if label not in GAS_CLASSES:
        raise ValueError(f"batch{batch}.dat line {line_no}: unknown gas class {label}")
    if len(values) != N_FEATURES or set(values) != set(range(1, N_FEATURES + 1)):
        raise ValueError(
            f"batch{batch}.dat line {line_no}: expected {N_FEATURES} features, got {len(values)}"
        )
    return [batch, label, *(values[i] for i in range(1, N_FEATURES + 1))]


def load_batch(batch: int, raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Load ``batch{n}.dat`` as a DataFrame with ``batch``, ``label`` and 128 feature columns."""
    if not 1 <= batch <= N_BATCHES:
        raise ValueError(f"batch must be 1-{N_BATCHES}, got {batch}")
    path = raw_dir / f"batch{batch}.dat"
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found — download the UCI dataset into {raw_dir}")

    with path.open() as fh:
        rows = [
            _row_from_line(line, batch, n) for n, line in enumerate(fh, start=1) if line.strip()
        ]

    df = pd.DataFrame(rows, columns=["batch", "label", *feature_columns()])
    return df.astype({"batch": "int64", "label": "int64"})


def load_batches(batches: range | list[int], raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Concatenate several batches into one DataFrame."""
    return pd.concat([load_batch(b, raw_dir) for b in batches], ignore_index=True)
